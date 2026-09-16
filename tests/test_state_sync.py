"""state_sync.sh (2026-09-14): the one transport for the runtime state dir,
run against a fake `kubectl` that executes the "remote" side locally with
the cluster paths rewritten into temp dirs. Locks the mirror semantics:
push is a full copy swapped into place (deleted files vanish from the
mirror), excludes .git/locks/temp files, keeps one dated backup per day
and prunes to 30; pull prefers the live controller and falls back to the
PVC mirror, replacing an old git clone; restore refuses a non-empty target
and an empty mirror. Mechanics only; no cluster."""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess
import tarfile

import pytest

ORCH = pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
SCRIPT = ORCH / "state_sync.sh"

_FAKE_KUBECTL = r'''#!/bin/bash
# Records the call, then runs the remote command LOCALLY with the cluster
# paths rewritten to the test's fake controller / PVC directories.
{ printf 'kubectl'; for a in "$@"; do printf ' %q' "$a"; done; echo; } >> "$TRACE"
args=(); for a in "$@"; do case "$a" in --kubeconfig=*) ;; *) args+=("$a");; esac; done
set -- "${args[@]}"
[ "$1" = exec ] || { echo "fake kubectl: only exec is faked" >&2; exit 1; }
shift; [ "$1" = "-i" ] && shift
target="$1"; shift; [ "$1" = "--" ] && shift
if [ "$target" = "hexapod-sweep-friction" ] && [ "${CONTROLLER_UP:-0}" != 1 ]; then
  echo "error: unable to upgrade connection: container not found" >&2; exit 1
fi
cmd=()
for a in "$@"; do
  a="${a//\/workspace\/hexapod\/.state/$FAKE_CONTROLLER}"
  a="${a//\/state/$FAKE_PVC}"
  cmd+=("$a")
done
exec "${cmd[@]}"
'''


@pytest.fixture
def cluster(tmp_path, monkeypatch):
    """Fake kubectl on PATH; returns (env, fake_pvc, fake_controller, trace)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    kubectl = bin_dir / "kubectl"
    kubectl.write_text(_FAKE_KUBECTL)
    kubectl.chmod(0o755)
    pvc = tmp_path / "pvc"
    (pvc / "hexapod").mkdir(parents=True)
    (pvc / "backups").mkdir()
    controller = tmp_path / "controller_state"
    trace = tmp_path / "trace.log"
    env = {**os.environ,
           "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "KUBECONFIG": str(tmp_path / "kube.yaml"),
           "TRACE": str(trace), "FAKE_PVC": str(pvc),
           "FAKE_CONTROLLER": str(controller), "CONTROLLER_UP": "0"}
    return env, pvc, controller, trace


def _state(root: pathlib.Path, runs: list[str], extra: bool = True) -> pathlib.Path:
    (root / "ledger").mkdir(parents=True, exist_ok=True)
    for i, run in enumerate(runs, 1):
        (root / "ledger" / f"{i:06d}-{run}.json").write_text(
            json.dumps({"run": run, "ledger_seq": i}, indent=2) + "\n")
    (root / "backlog.json").write_text("[]\n")
    (root / "RL_LOG.md").write_text("# log\n")
    if extra:
        (root / ".git").mkdir(exist_ok=True)
        (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (root / "experiments.json.lock").write_text("")
        (root / "ledger" / "000009-x.json.tmp123").write_text("{")
    return root


def _run(env, *args, state: pathlib.Path):
    return subprocess.run(["bash", str(SCRIPT), *args], env={**env, "HEXAPOD_STATE_DIR": str(state)},
                          capture_output=True, text=True, timeout=60)


def _ledger_names(root: pathlib.Path) -> list[str]:
    return sorted(p.name for p in (root / "ledger").iterdir())


def test_push_mirrors_a_full_copy_without_git_locks_or_temp_files(cluster, tmp_path):
    env, pvc, _, trace = cluster
    state = _state(tmp_path / "state", ["cw-a", "cw-b", "cw-c"])
    r = _run(env, "push", state=state)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines()[-1].startswith("state push: ") and " bytes -> deploy/hexapod-state:/state/hexapod in " in r.stdout
    mirror = pvc / "hexapod"
    assert _ledger_names(mirror) == ["000001-cw-a.json", "000002-cw-b.json", "000003-cw-c.json"]
    assert (mirror / "backlog.json").exists() and (mirror / "RL_LOG.md").exists()
    assert not (mirror / ".git").exists()
    assert not (mirror / "experiments.json.lock").exists()
    assert not list(pvc.glob("hexapod.incoming.*")) and not (pvc / "hexapod.prev").exists()
    assert "--kubeconfig=" in trace.read_text() and "exec -i deploy/hexapod-state" in trace.read_text()


def test_push_is_a_swap_so_deleted_files_leave_the_mirror(cluster, tmp_path):
    env, pvc, _, _ = cluster
    state = _state(tmp_path / "state", ["cw-a", "cw-b"])
    assert _run(env, "push", state=state).returncode == 0
    (state / "ledger" / "000001-cw-a.json").unlink()          # a dropped entry
    (state / "ledger" / "000003-cw-c.json").write_text(json.dumps({"run": "cw-c", "ledger_seq": 3}))
    r = _run(env, "push", state=state)
    assert r.returncode == 0, r.stderr
    assert _ledger_names(pvc / "hexapod") == ["000002-cw-b.json", "000003-cw-c.json"]


def test_push_writes_one_dated_backup_per_day_and_prunes_to_30(cluster, tmp_path):
    env, pvc, _, _ = cluster
    state = _state(tmp_path / "state", ["cw-a"])
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    for i in range(40):                                       # 40 stale days
        (pvc / "backups" / f"hexapod-state-2001{i // 30 + 1:02d}{i % 30 + 1:02d}.tgz").write_text("old")
    r = _run(env, "push", state=state)
    assert r.returncode == 0, r.stderr
    assert f"state backup: " in r.stdout and f"/backups/hexapod-state-{today}.tgz" in r.stdout
    kept = sorted(p.name for p in (pvc / "backups").iterdir())
    assert len(kept) == 30 and kept[-1] == f"hexapod-state-{today}.tgz"
    assert kept[0] == "hexapod-state-20010112.tgz"           # oldest 11 of 41 pruned
    with tarfile.open(pvc / "backups" / kept[-1]) as tf:
        assert "hexapod/ledger/000001-cw-a.json" in tf.getnames()
    first = (pvc / "backups" / kept[-1]).stat().st_mtime_ns
    r = _run(env, "push", state=state)                        # same day: no second backup
    assert r.returncode == 0 and "state backup:" not in r.stdout
    assert (pvc / "backups" / kept[-1]).stat().st_mtime_ns == first


def test_push_refuses_a_state_dir_without_a_ledger(cluster, tmp_path):
    env, pvc, _, _ = cluster
    empty = tmp_path / "state"
    empty.mkdir()
    r = _run(env, "push", state=empty)
    assert r.returncode != 0 and "holds no ledger" in r.stderr
    assert list((pvc / "hexapod").iterdir()) == []
    r = _run(env, "push", state=tmp_path / "nowhere")
    assert r.returncode != 0 and "state dir missing" in r.stderr


def test_push_fails_loudly_when_the_mirror_is_unreachable(cluster, tmp_path):
    env, _, _, _ = cluster
    state = _state(tmp_path / "state", ["cw-a"])
    (tmp_path / "blocked").write_text("a file where the mount should be")
    r = _run({**env, "FAKE_PVC": str(tmp_path / "blocked")}, "push", state=state)
    assert r.returncode != 0 and "push to deploy/hexapod-state:/state/hexapod failed" in r.stderr


def test_pull_prefers_the_live_controller_and_replaces_an_old_clone(cluster, tmp_path):
    env, pvc, controller, _ = cluster
    _state(controller, ["cw-live-1", "cw-live-2"])
    _state(pvc / "hexapod", ["cw-mirror"], extra=False)
    laptop = _state(tmp_path / "laptop" / ".state", ["cw-old"])   # has a .git from the retired repo
    r = _run({**env, "CONTROLLER_UP": "1"}, "pull", state=laptop)
    assert r.returncode == 0, r.stderr
    assert "state pull: controller hexapod-sweep-friction:/workspace/hexapod/.state (live)" in r.stdout
    assert "(2 ledger entries)" in r.stdout
    assert _ledger_names(laptop) == ["000001-cw-live-1.json", "000002-cw-live-2.json"]
    assert not (laptop / ".git").exists() and "was a git clone" in r.stderr
    assert not list((tmp_path / "laptop").glob(".state.*"))


def test_pull_falls_back_to_the_pvc_mirror_and_says_so(cluster, tmp_path):
    env, pvc, _, _ = cluster
    _state(pvc / "hexapod", ["cw-mirror"], extra=False)
    laptop = tmp_path / "laptop" / ".state"
    r = _run(env, "pull", state=laptop)                       # CONTROLLER_UP=0
    assert r.returncode == 0, r.stderr
    assert "controller hexapod-sweep-friction unreachable; pulling the PVC mirror" in r.stderr
    assert "state pull: PVC mirror deploy/hexapod-state:/state/hexapod" in r.stdout
    assert _ledger_names(laptop) == ["000001-cw-mirror.json"]


def test_pull_never_installs_an_empty_state_dir(cluster, tmp_path):
    env, pvc, _, _ = cluster                                  # mirror exists but is empty
    laptop = _state(tmp_path / "laptop" / ".state", ["cw-keep"], extra=False)
    r = _run(env, "pull", state=laptop)
    assert r.returncode != 0 and "holds no ledger" in r.stderr
    assert _ledger_names(laptop) == ["000001-cw-keep.json"]   # untouched
    assert not list((tmp_path / "laptop").glob(".state.incoming.*"))


def test_pull_resolves_a_symlinked_state_dir(cluster, tmp_path):
    env, pvc, _, _ = cluster
    _state(pvc / "hexapod", ["cw-mirror"], extra=False)
    real = _state(tmp_path / "shared_state", ["cw-old"], extra=False)
    link = tmp_path / "wt" / ".state"
    link.parent.mkdir()
    link.symlink_to(real, target_is_directory=True)
    r = _run(env, "pull", state=link)
    assert r.returncode == 0, r.stderr
    assert link.is_symlink() and _ledger_names(real) == ["000001-cw-mirror.json"]


def test_restore_populates_a_fresh_controller_only(cluster, tmp_path):
    env, pvc, _, _ = cluster
    fresh = tmp_path / "workspace" / ".state"
    r = _run(env, "restore", state=fresh)                      # empty mirror
    assert r.returncode != 0 and "holds no ledger" in r.stderr and not fresh.exists()
    _state(pvc / "hexapod", ["cw-m1", "cw-m2"], extra=False)
    r = _run(env, "restore", state=fresh)
    assert r.returncode == 0, r.stderr
    assert "state restore: deploy/hexapod-state:/state/hexapod ->" in r.stdout and "(2 ledger entries)" in r.stdout
    assert _ledger_names(fresh) == ["000001-cw-m1.json", "000002-cw-m2.json"]
    (fresh / "ledger" / "000003-cw-local.json").write_text("{}")
    r = _run(env, "restore", state=fresh)                      # non-empty target
    assert r.returncode != 0 and "is not empty" in r.stderr
    assert (fresh / "ledger" / "000003-cw-local.json").exists()
    r = _run(env, "restore", "--force", state=fresh)
    assert r.returncode == 0 and _ledger_names(fresh) == ["000001-cw-m1.json", "000002-cw-m2.json"]


def test_usage_and_shell_syntax():
    r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and "usage:" in r.stderr
    for name in ("state_sync.sh", "snapshot.sh", "setup_controller.sh", "ops.sh"):
        subprocess.run(["bash", "-n", str(ORCH / name)], check=True, timeout=30)
    snap = (ORCH / "snapshot.sh").read_text()
    assert 'state_sync.sh" push' in snap
    assert "git -C \"$STATE_DIR\"" not in snap                # state is not a repo any more
    assert "hexapod-state.git" not in (ORCH / "setup_controller.sh").read_text()
