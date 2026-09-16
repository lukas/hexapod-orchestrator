"""state_dir.sync_from_main: the one way controller code merges origin/main
into the orchestrator branch (watch_loop, status_server, restart_watcher).
It must merge (not rebase, so exp/* tags stay valid), report a conflict
without leaving the checkout half-merged, and be a no-op when up to date."""
from __future__ import annotations

import subprocess

import state_dir


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _repos(tmp_path):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "config", "user.email", "t@t"); _git(work, "config", "user.name", "t")
    (work / "a.txt").write_text("base\n")
    _git(work, "add", "a.txt"); _git(work, "commit", "-q", "-m", "base")
    _git(work, "push", "-q", "origin", "main")
    _git(work, "checkout", "-q", "-b", state_dir.ORCH_BRANCH)
    return origin, work


def _push_to_main(tmp_path, origin, filename, text):
    other = tmp_path / "other"
    if not other.exists():
        _git(tmp_path, "clone", "-q", str(origin), str(other))
        _git(other, "config", "user.email", "o@o"); _git(other, "config", "user.name", "o")
    _git(other, "checkout", "-q", "main"); _git(other, "pull", "-q")
    (other / filename).write_text(text)
    _git(other, "add", filename); _git(other, "commit", "-q", "-m", f"main: {filename}")
    _git(other, "push", "-q", "origin", "main")


def test_up_to_date_is_a_noop(tmp_path):
    _, work = _repos(tmp_path)
    head = _git(work, "rev-parse", "HEAD")
    assert state_dir.sync_from_main(work) is None
    assert _git(work, "rev-parse", "HEAD") == head


def test_merges_main_without_rewriting_branch_history(tmp_path):
    origin, work = _repos(tmp_path)
    (work / "orch.txt").write_text("orchestrator\n")
    _git(work, "add", "orch.txt"); _git(work, "commit", "-q", "-m", "snapshot")
    _git(work, "tag", "exp/run1")
    tagged = _git(work, "rev-parse", "exp/run1")
    _push_to_main(tmp_path, origin, "b.txt", "operator\n")

    assert state_dir.sync_from_main(work) is None
    assert (work / "b.txt").read_text() == "operator\n"
    assert (work / "orch.txt").exists()
    assert _git(work, "rev-parse", "exp/run1") == tagged          # merge, not rebase
    assert _git(work, "rev-parse", "--abbrev-ref", "HEAD") == state_dir.ORCH_BRANCH
    assert _git(work, "merge-base", "--is-ancestor", "origin/main", "HEAD") == ""


def test_conflict_is_reported_and_aborted(tmp_path):
    origin, work = _repos(tmp_path)
    (work / "a.txt").write_text("orchestrator edit\n")
    _git(work, "commit", "-q", "-am", "snapshot")
    _push_to_main(tmp_path, origin, "a.txt", "operator edit\n")
    head = _git(work, "rev-parse", "HEAD")

    err = state_dir.sync_from_main(work)
    assert err and "merge of origin/main failed" in err
    assert _git(work, "rev-parse", "HEAD") == head
    assert _git(work, "status", "--porcelain") == ""              # nothing half-merged
    assert (work / "a.txt").read_text() == "orchestrator edit\n"
