"""Where the orchestrator's runtime STATE lives, as opposed to the code.

The ledger (``experiments.json``), the launch queue (``backlog.json`` /
``backlog_failed.json``), the eval inbox (``pending_evals.json``), the
generated per-run stories (``rl_docs/runs/<run>.md``) and the append-only
cycle log (``RL_LOG.md``) are rewritten by machines many times an hour.
Until 2026-09-08 they were committed to ``lukas/hexapod`` ``main`` before
every launch, which put ~300 commits/day and a 27 MB JSON blob into the
code repo's history. They now live in their own repo:

    https://github.com/lukas/hexapod-state        (private)

cloned at ``<checkout>/.state`` on every machine, or wherever
``HEXAPOD_STATE_DIR`` points. ONE process writes it: the orchestrator on
the CoreWeave controller (``snapshot.sh`` commits + pushes it after every
run). Everyone else reads: ``make -C hexapod_walker/prototype_sts3215 state``
clones/pulls it locally, and ``status_server.py`` serves it on the web.

Every orchestrator script takes its paths from here. The module-level
constants (``LEDGER``, ``BACKLOG``, ``RUNS_DIR``, ...) are re-exported by
each script under the same names so tests can keep monkeypatching
``launch_run.LEDGER`` etc.

Two things are NOT plain symlinks on purpose: the JSON files are written
with write-temp-then-``os.replace``, and a rename onto a symlink replaces
the symlink with a regular file (silently forking the state), so the code
resolves the real path. ``rl_docs/runs`` is a directory symlink from the
prototype tree into ``.state`` (renames happen inside it, that is safe) so
every ``rl_docs/runs/<run>.md`` reference in prompts, docs and URLs still
works; ``RL_LOG.md`` is a file symlink for humans plus the real path here
for code, and ``snapshot.sh`` re-links it if an editor clobbers it.

Journals (2026-09-08): ``rl_docs/SKILLS.md``, ``OPERATOR_QUESTIONS.md`` and
``rl_docs/tracks/<track>/STATUS.md`` moved here too (same symlink pattern;
code only READS them via the symlinks). Cycles edit the ``.state/...`` path.
"""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent            # rl_move/orchestrator
PROTO = HERE.parents[1]                            # prototype_sts3215
REPO = PROTO.parents[1]                            # checkout root

STATE_REPO_URL = "https://github.com/lukas/hexapod-state.git"
SYNC_HINT = ("run `make -C hexapod_walker/prototype_sts3215 state` "
             "(clones/pulls lukas/hexapod-state into <checkout>/.state), "
             "or point HEXAPOD_STATE_DIR at an existing state clone")


def resolve_state_dir() -> Path:
    env = os.environ.get("HEXAPOD_STATE_DIR")
    if env:
        return Path(env).expanduser()
    return REPO / ".state"


STATE_DIR = resolve_state_dir()

LEDGER = STATE_DIR / "experiments.json"
LEDGER_LOCK = STATE_DIR / "experiments.json.lock"
BACKLOG = STATE_DIR / "backlog.json"
BACKLOG_LOCK = STATE_DIR / "backlog.json.lock"
BACKLOG_FAILED = STATE_DIR / "backlog_failed.json"
PENDING_EVALS = STATE_DIR / "pending_evals.json"
RUNS_DIR = STATE_DIR / "rl_docs" / "runs"
RL_LOG = STATE_DIR / "RL_LOG.md"


def require_state_dir(path: Path = None) -> Path:
    """Fail loudly (never with a fresh empty ledger) when state is missing."""
    d = STATE_DIR if path is None else path
    if not d.is_dir():
        raise FileNotFoundError(
            f"orchestrator state dir missing: {d} -- {SYNC_HINT}")
    return d


if __name__ == "__main__":
    print(STATE_DIR)
