"""Gate/owncfg idempotency must key on report.json, not bare dir
existence (pod_eval.py).

Bug found 08-28 (unified1-mix triage, chasing a stalled-forever
prestage): a partial/interrupted copy-back — e.g. a hand `kubectl cp`
that grabbed a still-computing remote artifact dir (videos present,
`report.json` not yet written) — left a directory that `local_out
.exists()` happily called "already on controller", writing the
prestage sentinel and releasing a verdict cycle to judge an incomplete
panel (confirmed live: two runs' gate/owncfg dirs, manually copied
mid-flight, were silently accepted as synced and the false
`_prestage.synced` sentinel got written). Every other pass in this
file (session/mixedsession/joygate) already keys on its own
completion file for exactly this reason; `core_pass_synced` brings
gate/owncfg in line and this test pins it directly.
"""
import importlib.util
import pathlib
import types

_ORCH = pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
_P = _ORCH / "pod_eval.py"
_spec = importlib.util.spec_from_file_location("pod_eval", _P)
pod_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pod_eval)

core_pass_synced = pod_eval.core_pass_synced
remote_report_exists = pod_eval.remote_report_exists


def _fake_kexec(returncode):
    def _f(pod, cmd, timeout=60):
        return types.SimpleNamespace(returncode=returncode, stdout="",
                                      stderr="")
    return _f


def test_remote_report_exists_true_when_test_dash_f_succeeds(monkeypatch):
    monkeypatch.setattr(pod_eval, "kexec", _fake_kexec(0))
    assert remote_report_exists("some-pod", "logs/ckpt_eval/foo_gate") is True


def test_remote_report_exists_false_when_test_dash_f_fails(monkeypatch):
    monkeypatch.setattr(pod_eval, "kexec", _fake_kexec(1))
    assert remote_report_exists("some-pod", "logs/ckpt_eval/foo_gate") is False


def test_remote_report_exists_checks_the_right_path(monkeypatch):
    seen = {}

    def _f(pod, cmd, timeout=60):
        seen["cmd"] = cmd
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(pod_eval, "kexec", _f)
    remote_report_exists("some-pod", "logs/ckpt_eval/foo_gate")
    assert "logs/ckpt_eval/foo_gate/report.json" in seen["cmd"]
    assert "test -f" in seen["cmd"]


def test_missing_dir_not_synced(tmp_path):
    assert core_pass_synced(tmp_path / "nope_gate") is False


def test_partial_copy_no_report_json_not_synced(tmp_path):
    # the exact shape a mid-flight `kubectl cp` leaves: videos/pngs
    # present, report.json not written yet because the remote eval
    # hasn't finished.
    d = tmp_path / "run_gate"
    d.mkdir()
    (d / "walk_sto_5.mp4").write_bytes(b"\x00")
    (d / "walk_sto_5.png").write_bytes(b"\x00")
    assert core_pass_synced(d) is False


def test_complete_pass_with_report_json_is_synced(tmp_path):
    d = tmp_path / "run_gate"
    d.mkdir()
    (d / "report.json").write_text("{}")
    assert core_pass_synced(d) is True
