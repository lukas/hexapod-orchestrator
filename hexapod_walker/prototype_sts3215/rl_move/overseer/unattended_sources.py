"""Bounded, model-free exports for an unattended metaagent review.

``collect_unattended`` writes the same ``{collected_at, data}`` envelopes as
the CLI's --codex-threads and --cloud-activity inputs. It never schedules a
review or starts/resumes a turn. Missing sources remain unknown.

Codex first uses the installed CLI's supported app-server proxy. If no live
daemon is reachable, a short-lived stdio app-server reads persisted metadata
with useStateDbOnly=True; EVERY status from that fallback is unknown. This
does not establish desktop liveness. Optional METAAGENT_CODEX_BIN and
METAAGENT_CODEX_CONTROL_SOCKET select the executable and existing socket.

Cloud authentication follows orchestrator/prepare_mcp_curl.py: the existing
rl_orchestrator entry in ~/.codex/config.toml, its literal/environment headers
and bearer_token_env_var. Only the documented endpoint and read tool are
allowed. A direct curl subprocess reads a private temporary config; no token
appears in argv, output errors, or exported envelopes. No app database or
transcript is opened by this module.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import tempfile
import time
import tomllib

from .collectors import _project_path
from .report import redact

RL_ENDPOINT = "https://hexapod.cwd1f0-new-cluster.coreweave.app/mcp"
RL_STRATEGY_URLS = {
    "research_brief": "https://hexapod.cwd1f0-new-cluster.coreweave.app/llm/brief.md",
    "recent_runs": "https://hexapod.cwd1f0-new-cluster.coreweave.app/llm/runs.md",
}
RL_STRATEGY_LIMITS = {"research_brief": 16_000, "recent_runs": 64_000}
MAX_BYTES = 1_500_000  # below the review CLI's two MB envelope limit
MAX_THREADS = 200
SOURCE_KINDS = ["cli", "vscode", "exec", "appServer", "subAgent", "subAgentReview",
                "subAgentCompact", "subAgentThreadSpawn", "subAgentOther", "unknown"]
_READ_METHODS = {"initialize", "thread/list"}


class SourceUnavailable(Exception):
    """Only static, credential-free error codes may cross the source boundary."""


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _error(source, code, detail):
    return {"source": source, "code": code, "detail": detail}


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceUnavailable("timeout")
    return remaining


def _json(raw):
    return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def _private_write(path: Path, data: bytes):
    fd, temporary = tempfile.mkstemp(prefix=".metaagent-source-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _envelope(path, data, *, mode, runtime_status_available=True):
    envelope = {"collected_at": _stamp(), "data": redact(data), "source_mode": mode,
                "runtime_status_available": runtime_status_available}
    raw = json.dumps(envelope, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise SourceUnavailable("payload_limit")
    _private_write(path, raw)
    return str(path.resolve())


class _AppServer:
    """JSONL reader with a shared deadline/byte cap, no turns or subscriptions."""

    def __init__(self, argv, deadline):
        self.deadline, self.buffer, self.received, self.ident = deadline, b"", 0, 0
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def close(self):
        self.selector.close()
        for pipe in (self.process.stdin, self.process.stdout):
            if pipe:
                pipe.close()
        if self.process.poll() is None:
            self.process.terminate()  # only this child proxy/inspector, never the daemon
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)

    def _send(self, request):
        try:
            self.process.stdin.write((json.dumps(request) + "\n").encode())
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            raise SourceUnavailable("app_server_unavailable") from None

    def request(self, method, params):
        if method not in _READ_METHODS:
            raise ValueError("Only inventory methods are allowed")
        self.ident += 1
        self._send({"jsonrpc": "2.0", "id": self.ident, "method": method, "params": params})
        while True:
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                try:
                    message = _json(line)
                except (ValueError, UnicodeError):
                    raise SourceUnavailable("invalid_app_server_response") from None
                if not isinstance(message, dict) or message.get("id") != self.ident:
                    # Notifications/requests are untrusted. Never execute/respond to them.
                    continue
                if "error" in message or not isinstance(message.get("result"), dict):
                    raise SourceUnavailable("app_server_request_failed")
                return message["result"]
            if not self.selector.select(_remaining(self.deadline)):
                raise SourceUnavailable("timeout")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise SourceUnavailable("app_server_unavailable")
            self.received += len(chunk)
            if self.received > MAX_BYTES:
                raise SourceUnavailable("payload_limit")
            self.buffer += chunk

    def initialize(self):
        self.request("initialize", {"clientInfo": {"name": "hexapod-metaagent-inventory", "version": "1.0"},
                                    "capabilities": {"experimentalApi": True}})
        self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})


def _thread_metadata(row, *, live):
    if not isinstance(row, dict) or not isinstance(row.get("id"), str):
        raise SourceUnavailable("invalid_app_server_response")
    state = row.get("status") or {}
    if not isinstance(state, dict):
        raise SourceUnavailable("invalid_app_server_response")
    status = {"active": "running", "idle": "idle", "systemError": "blocked"}.get(state.get("type"), "unknown")
    if state.get("type") == "active" and state.get("activeFlags"):
        status = "blocked"
    if not live:
        status = "unknown"
    # Deliberately exclude preview, turns, prompts, rollout paths and git remotes.
    result = {key: row[key] for key in ("id", "cwd", "projectId", "updatedAt", "parentThreadId", "model", "modelProvider")
              if isinstance(row.get(key), (str, int))}
    result.update(kind="codex", title=str(row.get("name") or row["id"])[:300], status=status)
    return redact(result)


def _inventory(argv, project_root, deadline, *, live):
    client = _AppServer(argv, deadline)
    rows, cursor, seen, scanned = [], None, set(), 0
    try:
        client.initialize()
        while scanned < MAX_THREADS:
            params = {"limit": min(100, MAX_THREADS - scanned), "archived": False,
                      "sortKey": "updated_at", "sortDirection": "desc", "sourceKinds": SOURCE_KINDS,
                      "useStateDbOnly": True}
            if cursor:
                params["cursor"] = cursor
            page = client.request("thread/list", params)
            raw_rows = page.get("data")
            if not isinstance(raw_rows, list) or len(raw_rows) > params["limit"]:
                raise SourceUnavailable("invalid_app_server_response")
            scanned += len(raw_rows)
            for row in raw_rows:
                item = _thread_metadata(row, live=live)
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                if _project_path(item.get("cwd"), project_root) or "hexapod" in item["title"].lower():
                    rows.append(item)
            next_cursor = page.get("nextCursor")
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise SourceUnavailable("invalid_app_server_response")
            if not next_cursor:
                return rows, False
            if next_cursor == cursor or not raw_rows:
                raise SourceUnavailable("invalid_app_server_pagination")
            cursor = next_cursor
        return rows, True
    finally:
        client.close()


def _codex_source(project_root, destination, timeout, codex_bin, codex_socket):
    source, errors = "codex:app-server", []
    binary = codex_bin or os.environ.get("METAAGENT_CODEX_BIN") or shutil.which("codex")
    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
    if not binary and bundled.is_file():
        binary = str(bundled)
    if not binary:
        raise SourceUnavailable("codex_executable_unavailable")
    deadline = time.monotonic() + timeout
    proxy = [str(binary), "app-server", "proxy"]
    socket = codex_socket or os.environ.get("METAAGENT_CODEX_CONTROL_SOCKET")
    if socket:
        proxy += ["--sock", str(socket)]
    live = True
    try:
        rows, truncated = _inventory(proxy, project_root, min(deadline, time.monotonic() + 5), live=True)
    except (SourceUnavailable, OSError):
        live = False
        errors.append(_error(source, "runtime_status_unavailable",
            "The live Codex app-server proxy is unavailable. Temporary stdio inventory contains persisted metadata only; all liveness is unknown."))
        rows, truncated = _inventory([str(binary), "app-server", "--stdio"], project_root, deadline, live=False)
    if truncated:
        errors.append(_error(source, "truncated", f"Only the {MAX_THREADS} most recently updated local threads were inspected; older active work may be absent."))
    data = {"schemaVersion": 4, "pinnedThreads": [], "threads": rows}
    path = _envelope(destination, data, mode="live_proxy" if live else "persisted_metadata",
                     runtime_status_available=live)
    return path, "partial" if errors else "available", errors


def _curl_configuration(home):
    """Same supported credentials as prepare_mcp_curl.py, in an isolated file."""
    config_path = home / ".codex/config.toml"
    try:
        with config_path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise SourceUnavailable("configuration_limit")
        server = tomllib.loads(raw.decode())["mcp_servers"]["rl_orchestrator"]
        if server.get("url") != RL_ENDPOINT:
            raise SourceUnavailable("unexpected_rl_endpoint")
        headers = dict(server.get("http_headers", {}))
        for name, variable in server.get("env_http_headers", {}).items():
            headers[name] = os.environ[variable]
        variable = server.get("bearer_token_env_var")
        if variable:
            headers["Authorization"] = "Bearer " + os.environ[variable]
        credentials = [value for key, value in headers.items() if key.lower() in {"authorization", "x-api-key"}]
        if not credentials or not all(isinstance(value, str) and value.strip() and value.strip() != "Bearer" for value in credentials):
            raise SourceUnavailable("authentication_unavailable")
        headers["Content-Type"] = "application/json"
        for key, value in headers.items():
            if not isinstance(key, str) or not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]+", key) or any(c in value for c in "\r\n\x00"):
                raise SourceUnavailable("invalid_authentication_configuration")
        lines = ["url = " + json.dumps(RL_ENDPOINT)]
        lines += ["header = " + json.dumps(f"{key}: {value}") for key, value in headers.items()]
        secrets = [*credentials, *(value[7:] for value in credentials if value.lower().startswith("bearer "))]
        return ("\n".join(lines) + "\n").encode(), secrets
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise SourceUnavailable("authentication_configuration_unavailable") from None


def _cloud_source(destination, timeout, home):
    config, secrets = _curl_configuration(home)
    # Each invocation owns its private files; no shared credential file races.
    with tempfile.TemporaryDirectory(prefix=".metaagent-rl-", dir=destination.parent) as private:
        config_path, response_path = Path(private) / "curl.conf", Path(private) / "response.json"
        _private_write(config_path, config)
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "orchestrator_activity", "arguments": {}}}
        argv = ["curl", "-q", "-f", "-sS", "--connect-timeout", str(min(10, timeout)),
                "--max-time", str(timeout), "--max-filesize", str(MAX_BYTES),
                "--config", str(config_path), "--data", json.dumps(request), "-o", str(response_path)]
        completed = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=timeout + 1, check=False)
        if completed.returncode:
            code = {22: "http_error", 28: "timeout", 63: "payload_limit"}.get(completed.returncode, "transport_unavailable")
            raise SourceUnavailable(code)
        with response_path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise SourceUnavailable("payload_limit")
        try:
            response = _json(raw)
        except (ValueError, UnicodeError):
            raise SourceUnavailable("invalid_mcp_response") from None
        result = response.get("result") if isinstance(response, dict) else None
        if not isinstance(result, dict) or response.get("error") or response.get("id") != 1 or result.get("isError"):
            raise SourceUnavailable("mcp_request_failed")
        content = result.get("content")
        if not isinstance(content, list) or not any(isinstance(item, dict) and item.get("type") == "text" for item in content):
            raise SourceUnavailable("invalid_mcp_response")
        # Discard auxiliary/raw structured fields. Existing cloud normalization
        # consumes bounded activity text and preserves log-source timestamps.
        text = "\n".join(item.get("text", "") for item in content
                         if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str))
        for secret in secrets:
            text = text.replace(secret, "[REDACTED]")
        path = _envelope(destination, {"content": [{"type": "text", "text": text}]}, mode="authenticated_mcp")
        return path, "available", []


def _strategy_source(destination, timeout):
    """Read bounded public campaign digests; these are evidence, not commands."""
    deadline = time.monotonic() + timeout
    data, errors = {}, []
    with tempfile.TemporaryDirectory(prefix=".metaagent-strategy-", dir=destination.parent) as private:
        for name, url in RL_STRATEGY_URLS.items():
            try:
                remaining = _remaining(deadline)
            except SourceUnavailable:
                errors.append(_error(f"rl:{name}", "timeout",
                                     "Strategic campaign evidence exceeded its time bound."))
                break
            response_path = Path(private) / f"{name}.txt"
            limit = RL_STRATEGY_LIMITS[name]
            argv = ["curl", "-q", "-f", "-L", "-sS", "--ignore-content-length", "--connect-timeout",
                    str(min(10, remaining)), "--max-time", str(remaining),
                    "--max-filesize", str(limit), url, "-o", str(response_path)]
            try:
                completed = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, timeout=remaining + 1, check=False)
            except subprocess.SubprocessError:
                errors.append(_error(f"rl:{name}", "timeout",
                                     "Strategic campaign evidence exceeded its time bound."))
                break
            try:
                raw = response_path.read_bytes()
            except OSError:
                errors.append(_error(f"rl:{name}", "source_unavailable",
                                     "Fresh strategic campaign evidence is unavailable."))
                continue
            # Curl returns nonzero after writing exactly the allowed prefix when
            # the public ledger is larger. That is our intended bounded read.
            truncated = completed.returncode != 0 and len(raw) == limit
            if completed.returncode and not truncated:
                errors.append(_error(f"rl:{name}", "transport_unavailable",
                                     "Fresh strategic campaign evidence is unavailable."))
                continue
            if len(raw) > limit:
                errors.append(_error(f"rl:{name}", "payload_limit",
                                     "Strategic campaign evidence exceeded its bounded read."))
                continue
            try:
                text = redact(raw.decode("utf-8", errors="ignore" if truncated else "strict"))
                data[name] = text + ("\n[bounded excerpt]" if truncated else "")
            except UnicodeError:
                errors.append(_error(f"rl:{name}", "invalid_response",
                                     "Strategic campaign evidence was not valid text."))
    if not data:
        raise SourceUnavailable("strategy_unavailable")
    path = _envelope(destination, data, mode="public_read_only")
    return path, "partial" if errors else "available", errors


def collect_unattended(project_root: Path, output_dir: Path, *, timeout_seconds: float = 30,
                       codex_bin: str | None = None, codex_socket: str | None = None,
                       home: Path | None = None) -> dict:
    """Collect independently; partial coverage must never imply comprehensive idle.

    Reads take at most the per-source timeout concurrently (plus child cleanup).
    Returned paths are fresh private JSON files, or None on failure. Old files
    at the three owned export paths are removed before collection. ``home`` only
    selects the RL credential configuration; Codex respects its own CLI config.
    Unknown cost is untouched; these requests never invoke an LLM.
    """
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError("timeout_seconds must be greater than zero and at most 60")
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    target.chmod(0o700)
    root, home = Path(project_root), Path(home) if home is not None else Path.home()
    paths = {"codex_threads": target / "codex-threads.json",
             "cloud_activity": target / "cloud-activity.json",
             "strategy_evidence": target / "strategy-evidence.json"}
    for path in paths.values():
        path.unlink(missing_ok=True)
    result = {"collected_at": _stamp(), "codex_threads": None, "cloud_activity": None,
              "strategy_evidence": None,
              "source_status": {}, "errors": []}
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="metaagent-source") as pool:
        pending = {"codex_threads": pool.submit(_codex_source, root, paths["codex_threads"], timeout, codex_bin, codex_socket),
                   "cloud_activity": pool.submit(_cloud_source, paths["cloud_activity"], timeout, home),
                   "strategy_evidence": pool.submit(_strategy_source, paths["strategy_evidence"], timeout)}
        for source, future in pending.items():
            try:
                path, status, errors = future.result()
                result[source], result["source_status"][source] = path, status
                result["errors"].extend(errors)
            except (SourceUnavailable, OSError, ValueError, subprocess.SubprocessError) as error:
                # Never copy subprocess stderr, exception repr, auth config or
                # remote error messages into output. Codes are ours exclusively.
                code = str(error) if isinstance(error, SourceUnavailable) else "source_unavailable"
                result["source_status"][source] = "unavailable"
                result["errors"].append(_error(source, code,
                    "Fresh source evidence is unavailable; activity and cost remain unknown."))
    return result
