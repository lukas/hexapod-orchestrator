import pytest
"""Duplicate-eval guard for pod_eval.py.

2026-08-27 (standwalk anchor14-rescue-acq8m idle-kick): pod_eval's old
idempotency check only asked "does the CONTROLLER-side artifact dir
already exist" — a pass still mid-flight on the pod (the normal state
for anything with per-mode video, easily 1-2h) was invisible to it, so
re-invoking `ops.sh podeval`/pod_eval.py on the same run silently
launched a SECOND eval_checkpoint tree on the same pod, racing the
first for CPU and for the same output-dir episode files. This test
pins `remote_eval_running`'s pure grep-matching logic (subprocess I/O
mocked — no real pod) so the guard can't silently regress.
"""
import importlib.util
import pathlib
import subprocess
import sys
import time
import types

_ORCH = pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
_P = _ORCH / "pod_eval.py"
_spec = importlib.util.spec_from_file_location("pod_eval", _P)
pod_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pod_eval)


def _fake_kexec(returncode, stdout=""):
    def _f(pod, cmd, timeout=60):
        return types.SimpleNamespace(returncode=returncode, stdout=stdout,
                                      stderr="")
    return _f


def test_match_found_reports_running(monkeypatch):
    monkeypatch.setattr(pod_eval, "kexec", _fake_kexec(
        0, "uv run python -m rl_move.sim.eval_checkpoint ... --out logs/ckpt_eval/foo_gate\n"))
    assert pod_eval.remote_eval_running("some-pod", "logs/ckpt_eval/foo_gate") is True


def test_no_match_reports_not_running(monkeypatch):
    monkeypatch.setattr(pod_eval, "kexec", _fake_kexec(1, ""))
    assert pod_eval.remote_eval_running("some-pod", "logs/ckpt_eval/foo_gate") is False


def test_pod_timeout_fails_open_not_running(monkeypatch):
    # A slow/unreachable pod must not permanently block a genuinely
    # ready re-eval — fail open (treat as "not running") like the old
    # behavior, rather than wedging the caller.
    def _timeout(pod, cmd, timeout=60):
        raise subprocess.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(pod_eval, "kexec", _timeout)
    assert pod_eval.remote_eval_running("some-pod", "logs/ckpt_eval/foo_gate") is False


def test_module_arg_is_used_in_grep(monkeypatch):
    seen = {}

    def _f(pod, cmd, timeout=60):
        seen["cmd"] = cmd
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(pod_eval, "kexec", _f)
    pod_eval.remote_eval_running("some-pod", "logs/ckpt_eval/foo_joygate",
                                  "rl_move.sim.eval_joystick_gate")
    assert "rl_move.sim.eval_joystick_gate" in seen["cmd"]
    assert "logs/ckpt_eval/foo_joygate" in seen["cmd"]


def _real_shell_kexec(pod, cmd, timeout=60):
    """Actually run remote_eval_running's own `ps | grep | grep | grep`
    pipeline through a real local `bash -c`, standing in for `kubectl
    exec` — no mocking of the match logic itself. This is the only way
    to catch the self-match bug this guards against: it lives in how
    the pipeline behaves as a REAL shell invocation (its own argv
    containing the search strings), which a mocked-kexec test can't
    see no matter what it asserts, since it never runs a real
    `ps`/`grep`. (Confirmed against the actual `hexapod-mjx-train-1`
    pod too, 2026-08-28: without the `grep -v grep` guard, `ps ww -eo
    args= | grep eval_session | grep -F -- <made-up-string>` returns
    rc=0 self-matching its own invocation; with the guard, rc=1.)"""
    return subprocess.run(["bash", "-c", cmd], capture_output=True,
                          text=True, timeout=timeout)


def test_self_match_regression_no_real_process_running(monkeypatch):
    """2026-08-28 regression (found chasing acq8m's silently-never-
    launched session pass): `kubectl exec pod -- bash -c "ps ww -eo
    args= | grep MODULE | grep -F -- OUT_REL"` is itself a process
    whose own argv contains both MODULE and OUT_REL as literal text —
    `ps -eo args=` lists that wrapper (and its `grep` children)
    alongside anything genuinely running, so the pipeline without a
    self-match guard ALWAYS matches, even with nothing real running
    (this is why the acq8m session pass silently never launched — no
    log, no crash, no real process, just a permanent false "already
    RUNNING"). Use a search string guaranteed to match no real process
    on this machine; the fixed `remote_eval_running` must return
    False for it."""
    monkeypatch.setattr(pod_eval, "kexec", _real_shell_kexec)
    made_up = "totally_made_up_string_no_such_run_xyz123"
    assert pod_eval.remote_eval_running(
        "unused-pod", made_up, "rl_move.sim.eval_session") is False


@pytest.mark.slow  # >5 s: sim rollout; default loop is -m "not slow"
@pytest.mark.skipif(sys.platform != "linux", reason="exec -a argv rewriting + pgrep semantics differ on macOS; the guard runs on the Linux controller")
def test_self_match_regression_still_detects_a_real_match(monkeypatch):
    """Companion to the self-match regression above: the `grep -v
    grep` self-defense must not blind the guard to an actual running
    target (a background process whose own argv contains both the
    module and out_rel tokens and does NOT contain the word "grep")."""
    monkeypatch.setattr(pod_eval, "kexec", _real_shell_kexec)
    out_rel = "logs/ckpt_eval/selfmatchtest_gate"
    proc = subprocess.Popen(
        ["bash", "-c",
         f"exec -a 'uv-run-python-m-rl_move.sim.eval_checkpoint---out-{out_rel}' "
         "sleep 10"])
    try:
        deadline = time.monotonic() + 5
        seen = False
        while time.monotonic() < deadline and not seen:
            seen = pod_eval.remote_eval_running(
                "unused-pod", out_rel, "rl_move.sim.eval_checkpoint")
            if not seen:
                time.sleep(0.2)
        assert seen is True
    finally:
        proc.terminate()
        proc.wait(timeout=5)
