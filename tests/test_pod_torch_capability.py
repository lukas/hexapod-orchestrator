"""pod_torch_capability.py — the durable CUDA-torch capability record.

Named [code] wait (arch/STATUS.md, STATUS.md WAITING-ON 08-15): the
`cw-arch-tf-r1b`/`-hard1`/`-hard2-r1` CUDA-torch install on train-1 was
a manual, ephemeral pip install with nothing recorded anywhere. This
module makes it durable: a recorded per-pod capability file, and a
strict `is_capable()` gate (half-verified records don't count) meant to
back a launcher-level `--device cuda` refusal. These tests cover the
pure record/gate logic with no live pod — kubectl-touching paths
(install/verify) are exercised manually against a real pod, not here.
"""
import importlib.util
import json
import pathlib
import sys

_P = (pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
      / "pod_torch_capability.py")
_spec = importlib.util.spec_from_file_location("pod_torch_capability", _P)
ptc = importlib.util.module_from_spec(_spec)
sys.modules["pod_torch_capability"] = ptc
_spec.loader.exec_module(ptc)


def _isolate(monkeypatch, tmp_path):
    cap = tmp_path / "pod_torch_capability.json"
    lock = tmp_path / "pod_torch_capability.json.lock"
    monkeypatch.setattr(ptc, "CAPFILE", cap)
    monkeypatch.setattr(ptc, "CAPFILE_LOCK", lock)
    return cap


def test_no_file_means_no_pod_is_capable(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert ptc.load() == {}
    assert ptc.is_capable("hexapod-mjx-train-1") is False


def test_fully_verified_record_is_capable(monkeypatch, tmp_path):
    cap = _isolate(monkeypatch, tmp_path)
    cap.write_text(json.dumps({
        "hexapod-mjx-train-1": {
            "torch_version": "2.11.0+cu128",
            "smoke": {"torch_cuda_available": True, "jax_import_ok": True},
        }
    }))
    assert ptc.is_capable("hexapod-mjx-train-1") is True
    # a pod with no record at all stays CPU-torch-default
    assert ptc.is_capable("hexapod-mjx-train-2") is False


def test_half_verified_record_is_not_capable(monkeypatch, tmp_path):
    """A record that exists but failed (or never ran) the coexistence
    smoke must NOT gate a --device cuda launch open — half-verified is
    not durable (this is the whole point vs the old ad hoc install)."""
    cap = _isolate(monkeypatch, tmp_path)
    cap.write_text(json.dumps({
        # torch installed but cuda not actually available on the probe
        "train-A": {"smoke": {"torch_cuda_available": False,
                              "jax_import_ok": True}},
        # jax broken (the real failure mode this whole module exists to
        # catch: torch stomping the pod's jax/warp stack)
        "train-B": {"smoke": {"torch_cuda_available": True,
                              "jax_import_ok": False}},
        # explicit probe error recorded
        "train-C": {"smoke": {"torch_cuda_available": True,
                              "jax_import_ok": True,
                              "torch_error": "ImportError: ..."}},
        # no smoke block at all (e.g. a stub record)
        "train-D": {"torch_version": "2.11.0+cu128"},
    }))
    for pod in ("train-A", "train-B", "train-C", "train-D"):
        assert ptc.is_capable(pod) is False, pod


def test_record_then_status_and_verify_roundtrip(monkeypatch, tmp_path, capsys):
    _isolate(monkeypatch, tmp_path)
    ns = ptc.argparse.Namespace(pod="hexapod-mjx-train-1",
                                version="2.11.0+cu128",
                                note="retroactive: cw-arch-tf-r1b/-hard1/"
                                     "-hard2-r1 evidence")
    rc = ptc.cmd_record(ns)
    assert rc == 0
    assert ptc.is_capable("hexapod-mjx-train-1") is True
    capsys.readouterr()
    rc = ptc.cmd_status(None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "hexapod-mjx-train-1" in out and "yes" in out


def test_probe_parser_handles_missing_marker():
    # kexec output with no CAPPROBE_JSON line (e.g. a kubectl warning on
    # stdout) must not raise — it's a diagnosable probe_error, not a crash.
    out = ptc._parse_probe("some unrelated stdout\n", "CAPPROBE_JSON:")
    assert "probe_error" in out


def test_probe_parser_extracts_json_from_noisy_output():
    noisy = "warning: some kubectl banner\nCAPPROBE_JSON:" + json.dumps(
        {"torch_version": "2.11.0+cu128", "torch_cuda_available": True,
         "jax_import_ok": True})
    out = ptc._parse_probe(noisy, "CAPPROBE_JSON:")
    assert out["torch_cuda_available"] is True
    assert out["jax_import_ok"] is True


def test_run_smoke_shell_quotes_multiline_python(monkeypatch):
    commands = []

    def fake_kexec(_pod, command, timeout=120):
        commands.append(command)
        if "FULLPROBE_JSON" in command:
            return "FULLPROBE_JSON:" + json.dumps({
                "cuda_matmul_ok": True,
                "cuda_matmul_finite": True,
                "jax_roundtrip_ok": True,
            })
        return "CAPPROBE_JSON:" + json.dumps({
            "torch_cuda_available": True,
            "jax_import_ok": True,
        })

    monkeypatch.setattr(ptc, "_kexec", fake_kexec)
    smoke = ptc._run_smoke("train-A", full=True)
    assert smoke["jax_roundtrip_ok"] is True
    smoke_commands = [command for command in commands
                      if "CAPPROBE_JSON" in command or "FULLPROBE_JSON" in command]
    assert smoke_commands
    assert all("uv run python -c '" in command for command in smoke_commands)
    assert all("\\n" not in command for command in commands)
    assert "==12.0" in ptc._FULL_SMOKE_PY


def test_install_records_additive_cuda_runtime(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    commands = []
    extra_calls = []

    def fake_kexec(_pod, command, timeout=120):
        commands.append(command)
        return ""

    smoke = {"torch_version": "2.11.0+cu128",
             "torch_cuda_available": True, "jax_import_ok": True,
             "cuda_matmul_ok": True, "cuda_matmul_finite": True,
             "jax_roundtrip_ok": True}
    monkeypatch.setattr(ptc, "_kexec", fake_kexec)
    monkeypatch.setattr(
        ptc, "_ensure_extra_cuda_libs",
        lambda pod: extra_calls.append(pod) or ["nvidia-cufile-cu12==1.14.1.1"])
    monkeypatch.setattr(ptc, "_run_smoke", lambda _pod, full: smoke)
    ns = ptc.argparse.Namespace(pod="train-A", version="", full_smoke=True)
    assert ptc.cmd_install(ns) == 0
    assert extra_calls == ["train-A"]
    assert "--index-url https://download.pytorch.org/whl/cu128" in commands[0]
    rec = ptc.load()["train-A"]
    assert rec["extra_cuda_libs_installed"] == [
        "nvidia-cufile-cu12==1.14.1.1"]
    assert rec["install_cmd"] == commands[0]


def test_extra_cuda_libs_are_installed_only_when_missing(monkeypatch):
    commands = []

    def fake_kexec(_pod, command, timeout=120):
        commands.append(command)
        if "import nvidia.cufile.lib" in command:
            raise ptc.subprocess.CalledProcessError(1, command)
        return ""

    monkeypatch.setattr(ptc, "_kexec", fake_kexec)
    installed = ptc._ensure_extra_cuda_libs("train-A")
    assert installed == ["nvidia-cufile-cu12==1.14.1.1"]
    installs = [command for command in commands
                if command.startswith("pip install")]
    assert installs == ["pip install nvidia-cufile-cu12==1.14.1.1 --no-deps"]
