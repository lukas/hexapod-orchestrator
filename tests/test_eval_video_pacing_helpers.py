"""Gate pacing requests must remain safe on old or unreachable evaluator pods."""
import importlib.util
import io
import json
import os
import pathlib
import shlex
import subprocess
import sys

import pytest

_ORCH = pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
_spec = importlib.util.spec_from_file_location("pod_eval_video_pacing", _ORCH / "pod_eval.py")
pod_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pod_eval)


def _target_source(tmp_path, source):
    target = tmp_path / "rl_move/sim/eval_checkpoint.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    if source == "new":
        target.write_text("VIDEO_PACING_API_VERSION = 1\n")
    elif source == "old":
        target.write_text("# evaluator without the optional pacing API\n")
    # Missing source makes the real grep fail with rc=2, unlike an old
    # evaluator's rc=1. Neither may be sent an unsupported argument.
    return target


@pytest.mark.parametrize(
    "source,hz,expected",
    [("new", 100, ["--video-fps", "25"]),
     ("new", 12.5, ["--video-fps", "12.5"]),
     ("old", 100, []), ("missing", 100, [])],
)
def test_pod_probe_real_shell_compatibility(state_ledger, monkeypatch, tmp_path, source, hz, expected):
    _target_source(tmp_path, source)
    monkeypatch.setattr(pod_eval, "POD_PROTO", str(tmp_path))
    seen = []

    def remote_shell(pod, command, timeout=60):
        seen.append((pod, timeout))
        return subprocess.run(["bash", "-c", command], capture_output=True,
                              text=True, timeout=timeout)

    monkeypatch.setattr(pod_eval, "kexec", remote_shell)
    assert shlex.split(pod_eval.eval_video_args("target-pod", hz)) == expected
    assert seen == [("target-pod", 15)]


@pytest.mark.parametrize("error", [OSError("unavailable"),
                                   subprocess.TimeoutExpired("probe", 15)])
def test_unavailable_probe_keeps_legacy_flags(monkeypatch, error):
    def unavailable(*args, **kwargs):
        raise error

    monkeypatch.setattr(pod_eval, "kexec", unavailable)
    assert pod_eval.eval_video_args("unavailable-pod", 100) == ""


def _gate_fixture(state_ledger, monkeypatch, tmp_path, hz=100, dr=0):
    run = "video-pacing-test-" + tmp_path.name
    state = state_ledger([{
        "run": run, "pod": "target-pod", "wandb_id": "test-id",
        "extra_args": ["--task", "joint_walk", "--cfg-set", f"control.hz={hz}",
                       "--dr-scale", str(dr)],
    }])
    monkeypatch.setattr(pod_eval, "PROTO", tmp_path)
    monkeypatch.setattr(pod_eval, "find_checkpoint",
                        lambda *args, **kwargs: "policy.zip")
    monkeypatch.setattr(pod_eval, "session_side", lambda *args: None)
    monkeypatch.setattr(pod_eval, "core_synced", lambda *args: None)
    monkeypatch.setattr(pod_eval, "core_pass_synced", lambda *args: False)
    monkeypatch.setattr(pod_eval, "remote_eval_running", lambda *args: False)
    monkeypatch.setattr(pod_eval, "remote_report_exists", lambda *args: False)
    monkeypatch.setattr(pod_eval, "open", lambda *args: io.StringIO(), raising=False)
    monkeypatch.setattr(sys, "argv", ["pod_eval.py", run])
    return run, state


def test_gate_and_owncfg_receive_pacing_after_one_probe(state_ledger, monkeypatch, tmp_path):
    _gate_fixture(state_ledger, monkeypatch, tmp_path, hz=12.5, dr=0.3)
    probes, launches = [], []

    def probe(pod, hz):
        probes.append((pod, hz))
        return " --video-fps 12.5"

    class CompletedEval:
        def wait(self, timeout):
            return 0

    def launch(args, **kwargs):
        launches.append(shlex.split(args[-1]))
        return CompletedEval()

    def copy(args, **kwargs):
        destination = pathlib.Path(args[-1])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "report.json").write_text("{}")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(pod_eval, "eval_video_args", probe)
    monkeypatch.setattr(pod_eval.subprocess, "Popen", launch)
    monkeypatch.setattr(pod_eval.subprocess, "run", copy)
    assert pod_eval.main() == 0
    assert probes == [("target-pod", 12.5)]
    assert len(launches) == 2
    for command in launches:
        assert command[command.index("--video-fps") + 1] == "12.5"
        assert command[command.index("--video-every") + 1] == "1"


@pytest.mark.parametrize("guard", ["synced", "running", "remote_complete"])
def test_existing_passes_never_probe_or_launch(state_ledger, monkeypatch, tmp_path, guard):
    _gate_fixture(state_ledger, monkeypatch, tmp_path)
    monkeypatch.setattr(pod_eval, "core_pass_synced", lambda *args: guard == "synced")
    monkeypatch.setattr(pod_eval, "remote_eval_running", lambda *args: guard == "running")
    monkeypatch.setattr(pod_eval, "remote_report_exists", lambda *args: guard == "remote_complete")
    copies = []

    def forbidden(*args, **kwargs):
        pytest.fail("an existing pass must not probe or launch")

    def copy(args, **kwargs):
        copies.append(args)
        destination = pathlib.Path(args[-1])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "report.json").write_text("{}")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(pod_eval, "eval_video_args", forbidden)
    monkeypatch.setattr(pod_eval.subprocess, "Popen", forbidden)
    monkeypatch.setattr(pod_eval.subprocess, "run", copy)
    assert pod_eval.main() == 0
    assert len(copies) == (1 if guard == "remote_complete" else 0)


@pytest.mark.parametrize(
    "source,hz,expected",
    [("new", 100, ["--video-fps", "25"]),
     ("new", 12.5, ["--video-fps", "12.5"]),
     ("old", 100, []), ("missing", 100, [])],
)
def test_evalcmd_probes_execution_target(state_ledger, monkeypatch, tmp_path, capsys, source, hz, expected):
    """Execute the real printed shell with a fake uv, never an evaluator.

    Generating on a new controller must not commit a command to flags that
    an old target pod cannot parse. The probe belongs in the printed script.
    """
    run, state = _gate_fixture(state_ledger, monkeypatch, tmp_path, hz=hz)
    monkeypatch.setenv("HEXAPOD_STATE_DIR", str(state))
    monkeypatch.setattr(sys, "argv", ["-", run])
    ops = (_ORCH / "ops.sh").read_text()
    section = ops.split("evalcmd) ", 1)[1].split("\nevalcmdstress)", 1)[0]
    code = section.split("<<'EOF'\n", 1)[1].split("\nEOF", 1)[0]
    exec(compile(code, str(_ORCH / "ops.sh") + ":evalcmd", "exec"), {})
    printed = capsys.readouterr().out
    # The target source appears only after command generation.
    _target_source(tmp_path, source)
    capture = tmp_path / "argv.bin"
    printed = printed.replace(f"/tmp/eval_{run}.log", str(tmp_path / "eval.log"))
    shell = (
        'uv() { printf "%s\\0" "$@" > "$CAPTURE"; }\n'
        'nohup() { "$@"; }\n' + printed + "\nwait\n"
    )
    result = subprocess.run(["bash", "-euo", "pipefail", "-c", shell], cwd=tmp_path,
                            env={**os.environ, "CAPTURE": str(capture)},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    argv = capture.read_bytes().decode().rstrip("\0").split("\0")
    assert argv[:5] == ["run", "python", "-m", "rl_move.sim.eval_checkpoint",
                        f"rl_move/sim/policies/ppo_goal_{run.replace('-', '_')}.zip"]
    assert argv[argv.index("--video-every") + 1] == "1"
    if expected:
        index = argv.index("--video-fps")
        assert argv[index:index + 2] == expected
    else:
        assert "--video-fps" not in argv
