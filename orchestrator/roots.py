"""Where things live. The orchestrator is its own checkout that operates on a
separate checkout of lukas/hexapod (the subject repo it launches, evaluates
and edits). Everything that touches a path resolves it through one of these:

ORCH_ROOT     this checkout (from __file__); own code, prompts, PAUSE/WRAPUP,
              the research-process docs at the root.
HEXAPOD_REPO  the hexapod checkout. $HEXAPOD_REPO, else the sibling
              ``../hexapod`` of this checkout if it exists, else
              ``/workspace/hexapod`` (the controller pod layout).
PROTO         HEXAPOD_REPO/hexapod_walker/prototype_sts3215 — the importable
              sim tree the trainers run from (rl_move/...).
STATE_DIR     runtime state (ledger dir, backlog, journals, run stories).
              $HEXAPOD_STATE_DIR, else ORCH_ROOT/.state.

Controller: /workspace/hexapod-orchestrator + /workspace/hexapod, state at
/workspace/hexapod/.state via HEXAPOD_STATE_DIR in /root/orchestrator.env.
"""
from __future__ import annotations

import os
from pathlib import Path

ORCH_ROOT = Path(__file__).resolve().parents[1]


def resolve_hexapod_repo() -> Path:
    env = os.environ.get("HEXAPOD_REPO")
    if env:
        return Path(env).expanduser().resolve()
    sibling = ORCH_ROOT.parent / "hexapod"
    if (sibling / "hexapod_walker" / "prototype_sts3215").is_dir():
        return sibling
    return Path("/workspace/hexapod")


def resolve_state_dir() -> Path:
    env = os.environ.get("HEXAPOD_STATE_DIR")
    if env:
        return Path(env).expanduser()
    return ORCH_ROOT / ".state"


HEXAPOD_REPO = resolve_hexapod_repo()
PROTO = HEXAPOD_REPO / "hexapod_walker" / "prototype_sts3215"
STATE_DIR = resolve_state_dir()
