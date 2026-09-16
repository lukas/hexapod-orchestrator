#!/usr/bin/env python3
"""Render a Claude Code stream-json cycle into a LIVE readable log.

Built 2026-08-21 (operator: "interactions with the orchestrator are way
too opaque — it should be easy to see everything going on"). Cycles
used to run `claude -p --output-format text`, which writes stdout ONLY
AT EXIT: the cycle log was a 0-byte file for the whole 10-30+ min a
cycle worked, and every watcher (human or LLM) was reduced to blind
polling. watch_loop.spawn_cycle now runs claude with
`--output-format stream-json --verbose` and pipes stdout through this
script, which appends a human-readable narration line to the cycle's
.log AS EACH EVENT ARRIVES (assistant text, every tool command, result
previews, the final verdict + cost) and mirrors the raw NDJSON events
to a sibling .jsonl for forensics.

Contract with the rest of the system (do not break):
- The narration goes to --out (the cycle_<stamp>_<label>.log the
  budget counters glob) and is APPEND-ONLY, line-buffered.
- The final `result` text is written VERBATIM under a
  "=== RESULT" heading — reap_cycles() greps the log tail for
  `^DIG-IN:` lines, so the model's final text must keep its line
  starts.
- The LAST line of a finished log is always "=== CYCLE END: <how> ==="
  (also written when the stream dies without a result event, e.g. a
  timeout kill). status_server / ops.sh / mcp_server use that marker
  to tell a finished cycle from a live one.
- NEVER crash: this process sits on claude's stdout pipe, so an
  unhandled exception here would SIGPIPE the cycle itself. Anything
  unparseable is passed through verbatim; render errors degrade to a
  one-line note.

Usage (spawned by watch_loop.py; hand-testable):
    claude -p ... --output-format stream-json --verbose "prompt" \
        | uv run python cycle_render.py --out cycle_X.log --raw cycle_X.jsonl
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys

MAX_CMD = 300      # chars of a tool command shown on its line
MAX_PREVIEW = 200  # chars of a tool result / thinking preview
MAX_ERR = 400      # chars of a tool error shown


def ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def _squash(text: str, cap: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= cap else text[: cap - 1] + "…"


def _tool_line(block: dict) -> str:
    """One line summarizing a tool_use block."""
    name = block.get("name", "?")
    inp = block.get("input") or {}
    if not isinstance(inp, dict):
        return f"$ [{name}] {_squash(inp, MAX_CMD)}"
    if "command" in inp:  # Bash
        line = f"$ {_squash(inp['command'], MAX_CMD)}"
        if inp.get("description"):
            line += f"   # {_squash(inp['description'], 80)}"
        return line
    if "file_path" in inp:  # Read/Write/Edit
        extra = ""
        if "old_string" in inp:
            extra = f" (edit: {_squash(inp['old_string'], 60)} -> " \
                    f"{_squash(inp.get('new_string', ''), 60)})"
        elif "content" in inp:
            extra = f" ({len(str(inp['content']))} chars)"
        return f"$ [{name}] {inp['file_path']}{extra}"
    if "pattern" in inp:  # Grep/Glob
        return f"$ [{name}] {_squash(inp['pattern'], 120)}" + (
            f" in {inp.get('path', '')}" if inp.get("path") else "")
    if "todos" in inp and isinstance(inp["todos"], list):
        states = ", ".join(
            _squash(f"{t.get('status', '?')}: {t.get('content', '')}", 60)
            for t in inp["todos"][:6])
        return f"$ [{name}] {states}"
    return f"$ [{name}] {_squash(json.dumps(inp), MAX_CMD)}"


def _result_text(content) -> str:
    """Flatten a tool_result content field (str or block list) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text")
    return str(content)


class Renderer:
    def __init__(self, out) -> None:
        self.out = out
        self.saw_result = False

    def line(self, text: str) -> None:
        self.out.write(f"[{ts()}] {text}\n")

    def raw_block(self, text: str) -> None:
        self.out.write(text.rstrip("\n") + "\n")

    def event(self, ev: dict) -> None:
        etype = ev.get("type", "")
        if etype == "system":
            if ev.get("subtype") == "init":
                self.line(f"=== CYCLE START: model={ev.get('model', '?')} "
                          f"session={ev.get('session_id', '?')} ===")
            return
        if etype == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                btype = block.get("type")
                if btype == "text" and block.get("text", "").strip():
                    self.line("agent:")
                    self.raw_block(block["text"])
                elif btype == "thinking" and block.get("thinking", "").strip():
                    self.line("thinking: "
                              + _squash(block["thinking"], MAX_PREVIEW))
                elif btype == "tool_use":
                    self.line(_tool_line(block))
            return
        if etype == "user":
            for block in (ev.get("message") or {}).get("content") or []:
                if not (isinstance(block, dict)
                        and block.get("type") == "tool_result"):
                    continue
                text = _result_text(block.get("content", "")).strip()
                if block.get("is_error"):
                    self.line("  ! ERROR: " + _squash(text, MAX_ERR))
                elif text:
                    n = text.count("\n") + 1
                    self.line(f"  -> {n} line{'s' if n != 1 else ''}: "
                              + _squash(text, MAX_PREVIEW))
                else:
                    self.line("  -> (no output)")
            return
        if etype == "result":
            self.saw_result = True
            dur = ev.get("duration_ms")
            dur = f"{int(dur) // 60000}m{(int(dur) // 1000) % 60:02d}s" \
                if dur else "?"
            cost = ev.get("total_cost_usd", ev.get("cost_usd"))
            cost = f"${cost:.2f}" if isinstance(cost, (int, float)) else "$?"
            self.line(f"=== RESULT: {ev.get('subtype', '?')} "
                      f"({ev.get('num_turns', '?')} turns, {dur}, {cost}) ===")
            text = ev.get("result")
            if isinstance(text, str) and text.strip():
                self.raw_block(text)  # verbatim: DIG-IN lines keep col 0
            self.raw_block(f"=== CYCLE END: {ev.get('subtype', '?')} ===")
            return
        if etype == "tool_progress":
            # The CLI emits one of these every ~30 s while a tool call
            # runs. Keep a compact line (it proves liveness and bumps
            # the log mtime that activity views report), not raw JSON
            # (observed cluttering the first deployed cycle, 08-22).
            self.line(f"... ({ev.get('tool_name', 'tool')} still running)")
            return
        # rate_limit_event, unknown types: one quiet line.
        if etype and etype != "stream_event":
            self.line(f"({etype}: {_squash(json.dumps(ev), 160)})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True,
                    help="narration log (appended, line-buffered)")
    ap.add_argument("--raw", default="",
                    help="optional raw NDJSON mirror of every event")
    args = ap.parse_args()
    out = open(args.out, "a", buffering=1, errors="replace")
    raw = open(args.raw, "a", buffering=1, errors="replace") \
        if args.raw else None
    r = Renderer(out)
    try:
        for line in sys.stdin:
            if raw is not None:
                try:
                    raw.write(line if line.endswith("\n") else line + "\n")
                except OSError:
                    raw = None  # disk trouble: keep narrating regardless
            stripped = line.strip()
            if not stripped:
                continue
            try:
                ev = json.loads(stripped)
                if not isinstance(ev, dict):
                    raise ValueError
            except ValueError:
                # claude stderr is merged into this pipe: pass through.
                r.raw_block(line)
                continue
            try:
                r.event(ev)
            except Exception as exc:  # never SIGPIPE the cycle
                r.line(f"(render error {exc!r} on: {_squash(stripped, 160)})")
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        try:
            if not r.saw_result:
                r.raw_block("=== CYCLE END: no-result "
                            "(stream closed early — killed or crashed) ===")
            out.close()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
