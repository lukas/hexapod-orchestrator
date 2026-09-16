"""Where the orchestrator's runtime STATE lives, as opposed to the code.

The ledger (``ledger/``), the launch queue (``backlog.json`` /
``backlog_failed.json``), the eval inbox (``pending_evals.json``), the
generated per-run stories (``rl_docs/runs/<run>.md``) and the append-only
cycle log (``RL_LOG.md``) are rewritten by machines many times an hour.
Until 2026-09-08 they were committed to ``lukas/hexapod`` ``main`` before
every launch (~300 commits/day, a 27 MB JSON blob in the code history);
until 2026-09-14 they were committed to a separate ``lukas/hexapod-state``
repo after every run, whose history reached 2.5 GB in a week. Git is not a
log. State is now a plain directory that is NOT a git repo:

    <checkout>/.state            (or wherever HEXAPOD_STATE_DIR points;
                                  controller: /workspace/hexapod/.state)

ONE process writes it: the orchestrator on the CoreWeave controller.
Durability is a mirror, not a repo: ``snapshot.sh`` runs
``state_sync.sh push`` after every run, which copies the directory onto
the ``hexapod-state`` PVC (``/state/hexapod`` on Deployment
``hexapod-state``) and keeps 30 daily ``.tgz`` backups there. Everyone
else reads: ``make -C hexapod_walker/prototype_sts3215 state``
(``state_sync.sh pull``) copies the live state from the controller (or
the PVC mirror) into ``<checkout>/.state``; ``status_server.py`` serves it
on the web; a fresh controller is populated with ``state_sync.sh restore``.

The ledger is a DIRECTORY of one JSON object per entry::

    ledger/000001-<run>.json
    ledger/000002-<run>.json
    ...

Every entry carries a persistent ``ledger_seq`` (assigned once, at its
first save: max existing + 1; the migration numbers the legacy list
1..N). The file name is ``<seq>-<run>.json``; the list order readers rely
on (LAST matching entry wins, and run names repeat for retries) is seq
order, so deleting an entry leaves a gap and never renumbers anything.
``load_ledger()`` and ``save_ledger()`` below are the ONLY accessors;
``save_ledger`` matches entries to files by seq, rewrites just the files
whose content changed (temp file + ``os.replace``), creates files for new
entries and deletes files whose seq is gone. Writers that REPLACE an entry
dict must carry its ``ledger_seq`` over (``launch_run.upsert_entry`` does);
a seq-less entry in the middle of the list is an error, not a re-append.
The single-file ``experiments.json`` is legacy: ``load_ledger`` refuses to
read it and names the migration command (``python state_dir.py
migrate-ledger``).

Every orchestrator script takes its paths from here (``BACKLOG``,
``RUNS_DIR``, ...). Tests point ``state_dir.LEDGER_DIR`` at a temp dir and
write fixtures with ``save_ledger``.

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

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent            # rl_move/orchestrator
PROTO = HERE.parents[1]                            # prototype_sts3215
REPO = PROTO.parents[1]                            # checkout root

SYNC_HINT = ("run `make -C hexapod_walker/prototype_sts3215 state` "
             "(state_sync.sh pull: copies the live state from the controller, "
             "or the PVC mirror, into <checkout>/.state), "
             "or point HEXAPOD_STATE_DIR at an existing state copy")
MIGRATE_CMD = ("uv run python hexapod_walker/prototype_sts3215/rl_move/"
               "orchestrator/state_dir.py migrate-ledger")


def resolve_state_dir() -> Path:
    env = os.environ.get("HEXAPOD_STATE_DIR")
    if env:
        return Path(env).expanduser()
    return REPO / ".state"


STATE_DIR = resolve_state_dir()

LEDGER_DIR = STATE_DIR / "ledger"          # one JSON object per entry
LEDGER = LEDGER_DIR                         # legacy name; the directory
LEGACY_LEDGER_NAME = "experiments.json"     # retired single-file ledger
LEDGER_LOCK = STATE_DIR / "experiments.json.lock"   # writers' flock (unchanged)
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
        "CURRENT_TRUTHS.md": "CURRENT_TRUTHS.md",
        "rl_docs/SKILLS.md": "rl_docs/SKILLS.md",
        "rl_move/orchestrator/OPERATOR_QUESTIONS.md": "OPERATOR_QUESTIONS.md",
    }
    if rel in fixed:
        return fixed[rel]
    parts = Path(rel).parts
    if (len(parts) == 3 and parts[:2] in (("rl_docs", "runs"),
                                          ("rl_docs", "meta"))) or (
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
    names.update(("RL_LOG.md", "CURRENT_TRUTHS.md", "rl_docs/SKILLS.md",
                  "rl_move/orchestrator/OPERATOR_QUESTIONS.md"))
    names.update(f"rl_docs/runs/{p.name}"
                 for p in (STATE_DIR / "rl_docs" / "runs").glob("*.md"))
    names.update(f"rl_docs/meta/{p.name}"
                 for p in (STATE_DIR / "rl_docs" / "meta").glob("*.md"))
    names.update(f"rl_docs/tracks/{p.parent.name}/STATUS.md"
                 for p in (STATE_DIR / "rl_docs" / "tracks").glob("*/STATUS.md"))
    return [rel for rel in sorted(names)
            if (p := document_path(rel, proto)) is not None and p.is_file()]


# Orchestrator CODE lives on its own branch (2026-09-14). main is deployed
# automatically to the controller, the robots and the Mac hub, and 70% of its
# history had become "orchestrator snapshot before <run>" commits, which made
# blame and bisect useless. snapshot.sh commits and pushes ORCH_BRANCH and
# merges origin/main into it; a human merges ORCH_BRANCH into main when the
# orchestrator's code changes are wanted there.
ORCH_BRANCH = os.environ.get("HEXAPOD_ORCH_BRANCH", "orchestrator")


def sync_from_main(repo: Path, lock: str | None = None, *,
                   blocking: bool = True, timeout: int = 300) -> str | None:
    """Merge origin/main into the checkout. Returns None on success, else why.

    The one implementation behind the watcher's pre-cycle sync, the status
    server's doc sync and the restart script. Merge, never rebase: exp/*
    tags must keep pointing at the commits they were made on. A conflict
    is aborted so the shared checkout is never left half-merged. With
    ``blocking=False`` a held lock skips the round (returns None).
    """
    import subprocess

    def git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True,
                              timeout=timeout, check=check)

    r = git("fetch", "-q", "origin", "main")
    if r.returncode != 0:
        return f"fetch failed: {(r.stderr or r.stdout)[-300:]}"
    if git("merge-base", "--is-ancestor", "origin/main", "HEAD").returncode == 0:
        return None
    merge = ["git", "-C", str(repo), "-c", "merge.autoStash=true",
             "merge", "--no-edit", "origin/main"]
    if lock:
        merge = ["flock", *([] if blocking else ["-n"]), lock, *merge]
    r = subprocess.run(merge, capture_output=True, text=True, timeout=timeout)
    if r.returncode == 0 or (lock and not blocking and r.returncode == 1):
        return None
    git("merge", "--abort")
    return f"merge of origin/main failed: {(r.stderr or r.stdout)[-300:]}"


def require_state_dir(path: Path = None) -> Path:
    """Fail loudly (never with a fresh empty ledger) when state is missing."""
    d = STATE_DIR if path is None else path
    if not d.is_dir():
        raise FileNotFoundError(
            f"orchestrator state dir missing: {d} -- {SYNC_HINT}")
    return d


# ---------------------------------------------------------------------------
# The ledger: a directory of per-entry files. load_ledger/save_ledger are the
# only accessors; every reader and writer in the orchestrator goes through
# them (tests monkeypatch state_dir.LEDGER_DIR).
# ---------------------------------------------------------------------------

SEQ_KEY = "ledger_seq"                     # persistent per-entry identity
_SEQ_WIDTH = 6
_ENTRY_RE = re.compile(r"^(\d{%d,})-(.*)\.json$" % _SEQ_WIDTH)
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def entry_seq(entry) -> int | None:
    """The entry's ``ledger_seq`` if it has a valid one."""
    v = entry.get(SEQ_KEY) if isinstance(entry, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def ledger_entry_name(seq: int, entry) -> str:
    """``000123-<run>.json``: seq first (order + identity), name for humans."""
    run = entry.get("run") if isinstance(entry, dict) else None
    safe = _UNSAFE.sub("_", str(run or "")).strip("._") or "unnamed"
    return f"{seq:0{_SEQ_WIDTH}d}-{safe[:180]}.json"


def _entry_bytes(entry) -> bytes:
    return (json.dumps(entry, indent=2) + "\n").encode()


def _index_ledger_dir(d: Path) -> dict[int, Path]:
    """seq -> file. Loud on a duplicate seq or a stray .json: both mean a
    write was interrupted or a human dropped a file in by hand, and
    guessing an order would be a silent fallback."""
    files: dict[int, Path] = {}
    for p in d.iterdir():
        if p.suffix != ".json":
            continue                      # *.json.tmp<pid> mid-write files
        m = _ENTRY_RE.match(p.name)
        if not m:
            raise RuntimeError(
                f"ledger dir {d} holds a file that is not NNNNNN-<run>.json: "
                f"{p.name} -- move it out; {MIGRATE_CMD} --force rebuilds "
                f"the directory from experiments.json.migrated-*")
        seq = int(m.group(1))
        if seq in files:
            raise RuntimeError(
                f"ledger dir {d} has two files for seq {seq}: "
                f"{files[seq].name} and {p.name} -- an interrupted save; "
                f"delete the stale one (the newer mtime is the current entry)")
        files[seq] = p
    return files


def _read_ledger_dir(d: Path) -> list:
    files = _index_ledger_dir(d)
    out = []
    for seq in sorted(files):
        e = json.loads(files[seq].read_bytes())
        if entry_seq(e) != seq:
            raise RuntimeError(
                f"{files[seq]}: {SEQ_KEY}={e.get(SEQ_KEY)!r} inside does not "
                f"match the file name -- hand-edited? the file name is the "
                f"identity; fix the field or the name")
        out.append(e)
    return out


def _assign_seqs(entries: list, existing_seqs) -> None:
    """Give seq-less entries a fresh seq (max known + 1, in list order).
    Only TAIL entries may lack one: a seq-less entry followed by a
    numbered one means a writer replaced a dict without carrying its
    ``ledger_seq`` over, and re-appending it would silently make an old
    attempt the run's newest."""
    seen: set[int] = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise TypeError(f"ledger entry {i} is {type(e).__name__}, not a dict")
        s = entry_seq(e)
        if s is None:
            if SEQ_KEY in e:
                raise ValueError(f"ledger entry {i} has invalid {SEQ_KEY}={e[SEQ_KEY]!r}")
            continue
        if s in seen:
            raise ValueError(f"two ledger entries carry {SEQ_KEY}={s} "
                             f"(run {e.get('run')!r}); copy an entry without its seq")
        seen.add(s)
    nxt = max([*existing_seqs, *seen], default=0) + 1
    numbered_after = False
    for e in reversed(entries):
        if entry_seq(e) is not None:
            numbered_after = True
        elif numbered_after:
            raise ValueError(
                f"ledger entry {e.get('run')!r} has no {SEQ_KEY} but is followed "
                f"by numbered entries -- a writer replaced the dict; carry "
                f"{SEQ_KEY} over instead of re-appending")
    for e in entries:
        if entry_seq(e) is None:
            e[SEQ_KEY] = nxt
            nxt += 1


def _write_ledger_dir(d: Path, entries: list) -> int:
    """Bring ``d`` to exactly ``entries`` (keyed by seq); returns the number
    of files written or removed. Files whose name AND bytes already match
    are not touched, so a save that changes one entry changes one file."""
    existing = _index_ledger_dir(d)
    _assign_seqs(entries, existing)
    changed = 0
    for entry in entries:
        seq = entry_seq(entry)
        target = d / ledger_entry_name(seq, entry)
        data = _entry_bytes(entry)
        old = existing.pop(seq, None)
        if old == target:
            try:
                if old.read_bytes() == data:
                    continue
            except OSError:
                pass
        tmp = target.with_name(target.name + f".tmp{os.getpid()}")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        changed += 1
        if old is not None and old != target:
            old.unlink(missing_ok=True)   # same seq, run renamed
    for stale in existing.values():        # seqs no longer in the list
        stale.unlink(missing_ok=True)
        changed += 1
    return changed


def _legacy_ledger(d: Path) -> Path:
    return d.parent / LEGACY_LEDGER_NAME


def load_ledger() -> list[dict]:
    """All ledger entries in seq order. Never reads ``experiments.json``:
    a legacy-only or half-migrated state dir is an error naming the fix."""
    d = LEDGER_DIR
    legacy = _legacy_ledger(d)
    if not d.is_dir():
        if legacy.exists():
            raise RuntimeError(
                f"ledger is still the single file {legacy}; the code reads "
                f"the directory {d} -- run `{MIGRATE_CMD}` (with the watcher "
                f"stopped) to convert it")
        require_state_dir(d.parent)
        return []
    if legacy.exists():
        raise RuntimeError(
            f"both {d} and {legacy} exist -- a half-finished migration or an "
            f"old writer; finish with `{MIGRATE_CMD}` or move "
            f"{legacy.name} aside (the directory is authoritative)")
    return _read_ledger_dir(d)


def save_ledger(entries: list[dict]) -> None:
    """Write ``entries`` as the ledger directory, touching only changed
    files (each via temp file + ``os.replace``, so a reader never sees a
    torn entry). New (seq-less tail) entries get their ``ledger_seq`` set
    IN PLACE on the caller's dict. Callers hold ``launch_run.ledger_lock()``
    for the read-modify-write; this function does not lock."""
    if not isinstance(entries, list):
        raise TypeError(f"ledger must be a list, got {type(entries).__name__}")
    d = LEDGER_DIR
    require_state_dir(d.parent)
    legacy = _legacy_ledger(d)
    if legacy.exists():
        raise RuntimeError(
            f"refusing to write {d} while {legacy} exists -- run "
            f"`{MIGRATE_CMD}` first")
    d.mkdir(exist_ok=True)
    _write_ledger_dir(d, entries)


def ledger_fingerprint() -> str:
    """Cheap change detector for the ledger (names, sizes, mtimes; no
    parsing). Used by the watcher's board fingerprint."""
    h = hashlib.sha256()
    d = LEDGER_DIR
    try:
        for p in sorted(d.iterdir()):
            if p.suffix != ".json":
                continue
            st = p.stat()
            h.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns}\n".encode())
    except OSError:
        h.update(b"?")
    return h.hexdigest()


def migrate_ledger(force: bool = False, out=None) -> int:
    """``python state_dir.py migrate-ledger [--force]``: experiments.json ->
    ledger/. Idempotent: a state dir that only has the directory is a
    no-op. Numbers the list 1..N (``ledger_seq``), writes, re-reads,
    asserts equality with the source, then renames the source to
    ``experiments.json.migrated-<UTC stamp>`` (nothing is deleted).
    Refuses to overwrite a non-empty directory unless ``force``."""
    out = sys.stdout if out is None else out
    d = LEDGER_DIR
    legacy = _legacy_ledger(d)
    require_state_dir(d.parent)
    present = [p for p in d.iterdir() if p.suffix == ".json"] if d.is_dir() else []
    if not legacy.exists():
        if present:
            print(f"ledger already migrated: {len(present)} files in {d}", file=out)
            return 0
        print(f"ERROR: nothing to migrate: no {legacy} and no {d}", file=out)
        return 2
    if present and not force:
        print(f"ERROR: {d} already has {len(present)} files; pass --force to "
              f"rebuild it from {legacy.name}", file=out)
        return 2
    src = json.loads(legacy.read_bytes())
    if not isinstance(src, list):
        print(f"ERROR: {legacy} is not a JSON list", file=out)
        return 2
    d.mkdir(exist_ok=True)
    if force:
        for p in d.iterdir():
            if p.is_file() and ".json" in p.suffixes:
                p.unlink()
    if any(SEQ_KEY in e for e in src if isinstance(e, dict)):
        print(f"ERROR: {legacy} already carries {SEQ_KEY} fields; it is not a "
              f"legacy ledger", file=out)
        return 2
    n = _write_ledger_dir(d, src)          # numbers src 1..N in list order
    back = _read_ledger_dir(d)
    stripped = [{k: v for k, v in e.items() if k != SEQ_KEY} for e in back]
    if back != src or stripped != json.loads(legacy.read_bytes()):
        raise RuntimeError(
            f"migration self-check FAILED: {d} re-reads differently from "
            f"{legacy}; {legacy.name} left in place, nothing renamed")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    kept = legacy.with_name(f"{legacy.name}.migrated-{stamp}")
    os.replace(legacy, kept)
    print(f"migrated {len(src)} entries -> {d} ({n} files written); "
          f"{legacy.name} renamed to {kept.name}", file=out)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "migrate-ledger":
        sys.exit(migrate_ledger(force="--force" in sys.argv[2:]))
    if len(sys.argv) > 1:
        print(f"usage: state_dir.py [migrate-ledger [--force]]  "
              f"(no args: print the state dir)", file=sys.stderr)
        sys.exit(2)
    print(STATE_DIR)
