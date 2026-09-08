"""Real local bash pipe/PID checks; no kubectl, PPO, or remote processes."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

import pytest

ORCH = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCH))
import launch_run as lr


def stop_test_group(proc):
    # This fresh session contains only this test's shell and bounded child.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    proc.communicate(timeout=3)


@pytest.mark.parametrize("legacy_and_list", [False, True])
def test_capture_closes_while_redirected_child_is_still_alive(tmp_path, legacy_and_list):
    workdir = tmp_path / "working directory"
    workdir.mkdir()
    log = tmp_path / "training log.txt"
    child_script = (
        'printf "ready:%s:%s\\n" "$LAUNCH_TEST" "$PWD"; '
        'printf "stderr-marker\\n" >&2; '
        'if IFS= read -r line; then echo stdin-leaked; else echo stdin-eof; fi; '
        'exec sleep 30'
    )
    train = '/bin/sh -c ' + shlex.quote(child_script)
    envp = "LAUNCH_TEST=preserved "
    command = lr._background_train_command(
        train, envp=envp, workdir=str(workdir), log=str(log))
    if legacy_and_list:
        # Exact old shell structure: the waiting AND-list wrapper owns
        # capture pipes even though the trainer itself redirects fd0/1/2.
        command = (f"cd {shlex.quote(str(workdir))} && {envp}nohup {train} "
                   f"> {shlex.quote(str(log))} 2>&1 < /dev/null & echo $!")
    proc = subprocess.Popen(
        ["bash", "-c", command], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True)
    try:
        # A real started child distinguishes inherited pipes from slow startup.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if log.exists() and "stdin-eof" in log.read_text():
                break
            time.sleep(0.01)
        content = log.read_text()
        assert f"ready:preserved:{workdir}" in content
        assert "stderr-marker" in content and "stdin-eof" in content
        assert "stdin-leaked" not in content
        if legacy_and_list:
            with pytest.raises(subprocess.TimeoutExpired):
                proc.communicate(timeout=0.3)
        else:
            stdout, stderr = proc.communicate(timeout=3)
            assert proc.returncode == 0
            assert stderr == ""
            child_pid = int(stdout.strip())
            assert child_pid != proc.pid
            os.kill(child_pid, 0)  # alive after both captured streams reached EOF
    finally:
        stop_test_group(proc)


def test_failed_cd_aborts_before_starting_trainer(tmp_path):
    marker = tmp_path / "unexpected child"
    log = tmp_path / "unexpected log"
    train = '/bin/sh -c ' + shlex.quote('touch ' + shlex.quote(str(marker)))
    command = lr._background_train_command(
        train, envp="LAUNCH_TEST=preserved ",
        workdir=str(tmp_path / "missing directory"), log=str(log))
    result = subprocess.run(["bash", "-c", command], capture_output=True,
                            text=True, timeout=3)
    assert result.returncode != 0
    assert result.stdout == ""  # no fake background PID
    assert "missing directory" in result.stderr
    assert not marker.exists()
    assert not log.exists()
