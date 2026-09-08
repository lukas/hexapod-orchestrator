"""Run the sanctioned restart shell against isolated command doubles."""
import os
import pathlib
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
  tmux)
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


def _run_restart(tmp_path, *, sync_rc=0, lock_rc=0, parse_rc=0, active_polls=0):
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
    result = subprocess.run(
        ["bash", str(script)], cwd=tmp_path, timeout=15,
        env={**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
             "TRACE": str(trace), "PS_COUNT": str(count),
             "ACTIVE_POLLS": str(active_polls), "LOCK_RC": str(lock_rc),
             "SYNC_RC": str(sync_rc), "PARSE_RC": str(parse_rc),
             "OLD_WATCHER": str(old), "NEW_WATCHER": str(new)},
        capture_output=True, text=True)
    events = trace.read_text().splitlines()
    assert not (orch / "PAUSE").exists()
    assert not (orch / "WRAPUP").exists()
    assert not any("ERROR inherited snapshot lock" in event for event in events)
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
