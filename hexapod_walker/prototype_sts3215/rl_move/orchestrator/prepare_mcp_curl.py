"""Prepare private curl credentials for the configured RL MCP (no network I/O)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import tomllib


def main() -> None:
    config_path = Path.home() / ".codex" / "config.toml"
    config = tomllib.loads(config_path.read_text())
    server = config["mcp_servers"]["rl_orchestrator"]
    endpoint = "https://hexapod.cwd1f0-new-cluster.coreweave.app/mcp"
    if server.get("url") != endpoint:
        raise SystemExit("RL MCP endpoint differs from the documented endpoint.")

    headers = dict(server.get("http_headers", {}))
    for name, variable in server.get("env_http_headers", {}).items():
        if variable not in os.environ:
            raise SystemExit(f"Configured MCP header environment variable is missing: {variable}")
        headers[name] = os.environ[variable]
    token_variable = server.get("bearer_token_env_var")
    if token_variable:
        token = os.environ.get(token_variable)
        if not token:
            raise SystemExit(f"Configured MCP token environment variable is missing: {token_variable}")
        headers["Authorization"] = f"Bearer {token}"
    if not any(name.lower() in {"authorization", "x-api-key"} for name in headers):
        raise SystemExit("Existing RL MCP authentication was not found in Codex configuration.")
    headers["Content-Type"] = "application/json"
    for name, value in headers.items():
        if any(c in name + value for c in "\r\n"):
            raise SystemExit("Invalid newline in configured MCP header.")

    destination = Path("/tmp/hexapod-mcp-read.conf")
    fd, temporary = tempfile.mkstemp(prefix=".hexapod-mcp-", dir=destination.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write("url = " + json.dumps(endpoint) + "\n")
            for name, value in headers.items():
                handle.write("header = " + json.dumps(f"{name}: {value}") + "\n")
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print(f"Prepared {destination} with mode 600; credentials were not printed.")


if __name__ == "__main__":
    main()
