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
``rl_docs/tracks/<track>/STATUS.md`` moved here too. The symlinks preserve
human read paths; service readers use ``document_path``/``document_paths``
so overrides of the state location also apply to docs and discovery.
Cycles edit the ``.state/...`` path.
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


def state_doc_relative(rel: str) -> str | None:
    """Map a prototype-relative journal/story name into the state repo."""
    fixed = {
        "RL_LOG.md": "RL_LOG.md",
        "rl_docs/SKILLS.md": "rl_docs/SKILLS.md",
        "rl_move/orchestrator/OPERATOR_QUESTIONS.md": "OPERATOR_QUESTIONS.md",
    }
    if rel in fixed:
        return fixed[rel]
    parts = Path(rel).parts
    if (len(parts) == 3 and parts[:2] == ("rl_docs", "runs")) or (
        len(parts) == 4 and parts[:2] == ("rl_docs", "tracks")
        and parts[-1] == "STATUS.md"
    ):
        return rel
    return None


def document_path(rel: str, proto: Path | None = None) -> Path | None:
    """Resolve a logical doc in the configured state or code tree safely.

    The checked-in symlinks always target checkout/.state. Resolve journal
    names explicitly so HEXAPOD_STATE_DIR also governs docs on other clones.
    Missing files remain missing; this read path never creates state.
    """
    proto = PROTO if proto is None else proto
    if not rel.endswith(".md") or ".." in rel or Path(rel).is_absolute():
        return None
    state_rel = state_doc_relative(rel)
    candidate = STATE_DIR / state_rel if state_rel else proto / rel
    try:
        resolved = candidate.resolve()
        if (resolved.is_relative_to(proto.resolve())
                or resolved.is_relative_to(STATE_DIR.resolve())):
            return resolved
    except (OSError, RuntimeError):  # inaccessible paths or symlink loops
        pass
    return None


def track_status_paths(proto: Path | None = None) -> list[Path]:
    """Discover track journals, including tracks created only in state."""
    proto = PROTO if proto is None else proto
    names = {
        f"rl_docs/tracks/{p.parent.name}/STATUS.md"
        for root in (proto, STATE_DIR)
        for p in (root / "rl_docs" / "tracks").glob("*/STATUS.md")
    }
    return [p for rel in sorted(names)
            if (p := document_path(rel, proto)) is not None and p.is_file()]


def document_paths(proto: Path | None = None,
                   skip_dirs: set[str] | None = None) -> list[str]:
    """Index code docs plus state docs under their stable logical names.

    Do not follow arbitrary directory links: enumerate the known state
    locations explicitly, so loops and links to unrelated trees stay out.
    """
    proto = PROTO if proto is None else proto
    names = set()
    for root, dirs, files in os.walk(proto):
        dirs[:] = [d for d in dirs if d not in (skip_dirs or set())]
        for name in files:
            if name.endswith(".md"):
                names.add((Path(root) / name).relative_to(proto).as_posix())
    names.update(("RL_LOG.md", "rl_docs/SKILLS.md",
                  "rl_move/orchestrator/OPERATOR_QUESTIONS.md"))
    names.update(f"rl_docs/runs/{p.name}"
                 for p in (STATE_DIR / "rl_docs" / "runs").glob("*.md"))
    names.update(f"rl_docs/tracks/{p.parent.name}/STATUS.md"
                 for p in (STATE_DIR / "rl_docs" / "tracks").glob("*/STATUS.md"))
    return [rel for rel in sorted(names)
            if (p := document_path(rel, proto)) is not None and p.is_file()]


def require_state_dir(path: Path = None) -> Path:
    """Fail loudly (never with a fresh empty ledger) when state is missing."""
    d = STATE_DIR if path is None else path
    if not d.is_dir():
        raise FileNotFoundError(
            f"orchestrator state dir missing: {d} -- {SYNC_HINT}")
    return d


if __name__ == "__main__":
    print(STATE_DIR)
