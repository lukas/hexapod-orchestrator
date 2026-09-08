"""Run the sanctioned restart shell against isolated command doubles."""
import os
import pathlib
import shutil
import time
import subprocess

import pytest


_SCRIPT = (pathlib.Path(__file__).resolve().parents[1]
           / "orchestrator/restart_watcher.sh")

_MOCK = """#!/bin/bash
name=$(basename "$0")
{
  printf '%s' "$name"
  for arg in "$@"; do printf '|%s' "$arg"; done
  printf '\\n'
} >> "$TRACE"
case "$name" in
  ps)
    count=$(cat "$PS_COUNT")
    count=$((count + 1))
    echo "$count" > "$PS_COUNT"
    if [ "$count" -le "$ACTIVE_POLLS" ]; then
      echo 'worker claude -p --bare'
    fi
    ;;
  flock)
    if [ "$1" = "-n" ]; then
      "$REAL_UV" run --no-project --offline python - "$4" <<'PY'
import fcntl, sys
try:
    fcntl.flock(int(sys.argv[1]), fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(75)
PY
      exit $?
    fi
    test -e /dev/fd/9 || exit 80
    exit "$LOCK_RC"
    ;;
  git)
    test -e /dev/fd/9 || exit 81
    exit "$SYNC_RC"
    ;;
  uv)
    exit "$PARSE_RC"
    ;;
  sleep)
    if [ "$1" = "$SLEEP_TARGET" ]; then
      touch "$SLEEPING"
      while [ ! -f "$RELEASE" ]; do /bin/sleep 0.02; done
    fi
    ;;
  tmux)
    if [ -e /dev/fd/8 ]; then
      echo 'ERROR inherited lifetime restart lock' >> "$TRACE"
      exit 83
    fi
    if [ -e /dev/fd/9 ]; then
      echo 'ERROR inherited snapshot lock' >> "$TRACE"
      exit 82
    fi
    case "$1" in
      kill-session) rm -f "$OLD_WATCHER";;
      new-session) touch "$NEW_WATCHER";;
      has-session) test -f "$NEW_WATCHER";;
    esac
    ;;
esac
"""


def _setup_restart(tmp_path, *, sync_rc=0, lock_rc=0, parse_rc=0,
                   active_polls=0, sleep_target=""):
    # Only absolute host paths are relocated; all shell control flow is real.
    workspace = tmp_path / "workspace"
    repo = workspace / "hexapod"
    orch = repo / "hexapod_walker/prototype_sts3215/rl_move/orchestrator"
    orch.mkdir(parents=True)
    script = tmp_path / "restart_watcher.sh"
    runtime_env = tmp_path / "orchestrator.env"
    runtime_env.write_text("")
    script.write_text(
        _SCRIPT.read_text().replace("/workspace", str(workspace))
        .replace("/root/orchestrator.env", str(runtime_env))
        .replace("/tmp/pause_drain.log", str(tmp_path / "pause_drain.log")))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("ps", "flock", "git", "uv", "tmux", "sleep", "pkill"):
        path = bin_dir / name
        path.write_text(_MOCK)
        path.chmod(0o755)
    trace = tmp_path / "trace"
    count = tmp_path / "ps_count"
    count.write_text("0")
    old, new = tmp_path / "old_watcher", tmp_path / "new_watcher"
    old.touch()
    env = {
        **os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "TRACE": str(trace), "PS_COUNT": str(count), "REAL_UV": shutil.which("uv"),
        "ACTIVE_POLLS": str(active_polls), "LOCK_RC": str(lock_rc),
        "SYNC_RC": str(sync_rc), "PARSE_RC": str(parse_rc),
        "OLD_WATCHER": str(old), "NEW_WATCHER": str(new),
        "SLEEP_TARGET": str(sleep_target), "SLEEPING": str(tmp_path / "sleeping"),
        "RELEASE": str(tmp_path / "release"),
    }
    return script, env, orch, trace, old, new


def _run_restart(tmp_path, **options):
    script, env, orch, trace, old, new = _setup_restart(tmp_path, **options)
    result = subprocess.run(
        ["bash", str(script)], cwd=tmp_path, timeout=15, env=env,
        capture_output=True, text=True)
    events = trace.read_text().splitlines()
    assert not (orch / "PAUSE").exists()
    assert not (orch / "WRAPUP").exists()
    assert not any("ERROR inherited" in event for event in events)
    return result, events, old, new


@pytest.mark.parametrize("failure", ["pull", "lock"])
def test_failed_sync_leaves_old_watcher_running_and_clears_flags(tmp_path, failure):
    result, events, old, new = _run_restart(
        tmp_path, sync_rc=1 if failure == "pull" else 0,
        lock_rc=1 if failure == "lock" else 0)
    assert result.returncode == 1
    assert old.exists() and not new.exists()
    assert "repository sync failed; leaving old watcher running" in result.stdout
    assert not any(event.startswith(("tmux|", "uv|")) for event in events)
    assert "flock|-w|120|9" in events
    git = [event for event in events if event.startswith("git|")]
    assert len(git) == (1 if failure == "pull" else 0)


def test_successful_sync_is_locked_fast_forward_without_autostash(tmp_path):
    result, events, old, new = _run_restart(tmp_path, active_polls=3)
    assert result.returncode == 0, result.stderr
    assert not old.exists() and new.exists()
    assert "RESTARTED ok" in result.stdout
    git = "git|-c|rebase.autoStash=false|-c|merge.autoStash=false|pull|--no-rebase|--ff-only|origin|main"
    assert git in events
    assert events.index("flock|-w|120|9") < events.index(git)
    assert events.index(git) < events.index("tmux|kill-session|-t|orchestrator")
    # Existing wrapup cadence/drain survives: three cycles polls, drain at #2.
    assert events.count("sleep|60") == 3
    drains = [i for i, event in enumerate(events)
              if event == "uv|run|python|rl_move/orchestrator/launch_run.py|drain"]
    assert len(drains) == 1 and drains[0] < events.index(git)
    assert not any(event.startswith("pkill|") for event in events)


def test_parse_failure_still_preserves_old_watcher(tmp_path):
    result, events, old, new = _run_restart(tmp_path, parse_rc=1)
    assert result.returncode == 1
    assert old.exists() and not new.exists()
    assert "watch_loop.py failed to parse" in result.stdout
    assert not any(event.startswith("tmux|") for event in events)


def test_wrapup_deadline_still_terminates_only_stragglers_before_sync(tmp_path):
    result, events, old, new = _run_restart(tmp_path, active_polls=999)
    assert result.returncode == 0, result.stderr
    assert events.count("sleep|60") == 30
    assert events.count("pkill|-TERM|-f|claude -p --bare") == 1
    assert events.index("pkill|-TERM|-f|claude -p --bare") < events.index("flock|-w|120|9")
    assert not old.exists() and new.exists()


@pytest.mark.parametrize("sleep_target", ["60", "5"])
def test_concurrent_restart_is_noop_through_verification(tmp_path, sleep_target):
    """Use a real cross-process flock, with only host commands doubled.

    Hold the owner during cycle wrapup (flags exist) and during replacement
    verification (flags cleared). A second invocation must mutate neither.
    """
    script, env, orch, trace, old, new = _setup_restart(
        tmp_path, active_polls=1 if sleep_target == "60" else 0,
        sleep_target=sleep_target)
    owner = subprocess.Popen(["bash", str(script)], cwd=tmp_path, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not pathlib.Path(env["SLEEPING"]).exists():
            assert owner.poll() is None, owner.communicate()
            assert time.monotonic() < deadline, "owner never reached the test barrier"
            time.sleep(0.02)
        before = {name: (orch / name).stat().st_mtime_ns
                  if (orch / name).exists() else None for name in ("PAUSE", "WRAPUP")}
        assert all(value is not None for value in before.values()) == (sleep_target == "60")
        events_before = len(trace.read_text().splitlines())
        duplicate = subprocess.run(
            ["bash", str(script)], cwd=tmp_path, env=env,
            capture_output=True, text=True, timeout=10)
        assert duplicate.returncode == 0, duplicate.stderr
        assert "restart already owned" in duplicate.stdout
        assert owner.poll() is None
        assert {name: (orch / name).stat().st_mtime_ns
                if (orch / name).exists() else None for name in before} == before
        assert trace.read_text().splitlines()[events_before:] == ["flock|-n|-E|75|8"]
    finally:
        pathlib.Path(env["RELEASE"]).touch()
        stdout, stderr = owner.communicate(timeout=10)
    assert owner.returncode == 0, stderr
    assert "RESTARTED ok" in stdout
    assert not old.exists() and new.exists()
    assert not (orch / "PAUSE").exists() and not (orch / "WRAPUP").exists()
    assert "ERROR inherited" not in trace.read_text()
    # Owner exit releases the lock; it was not inherited by tmux/the watcher.
    import fcntl
    with open(tmp_path / "workspace/restart_watcher.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
