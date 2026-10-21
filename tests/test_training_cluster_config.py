"""Explicit worker-cluster selection must reach launches and watcher probes."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_worker_commands_use_explicit_cluster_without_contacting_coreweave(tmp_path, monkeypatch):
    kubeconfig = tmp_path / "puget training.yaml"
    # Deliberately absent: selecting an unavailable explicit cluster must still
    # fail there, rather than silently redirect work to the retired fleet.
    monkeypatch.setenv("KUBECONFIG", str(kubeconfig))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HEXAPOD_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HEXAPOD_REPO", str(tmp_path / "subject"))
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("PYTHONPATH", str(root / "orchestrator"))
    code = '''
import json, subprocess
from types import SimpleNamespace
import launch_run, pod_torch_capability, watch_loop
calls = []
def run(cmd, **kwargs):
    calls.append(cmd)
    return SimpleNamespace(stdout="", returncode=0)
subprocess.run = run
launch_run.kexec("puget1-gpu", "true")
pod_torch_capability._kexec("puget1-gpu", "true")
watch_loop.live_unregistered_evals()
print(json.dumps([c for c in calls if c[0] == "kubectl"]))
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, check=True, timeout=5, env=os.environ.copy())
    commands = json.loads(result.stdout)
    assert len(commands) == 3
    assert all(c[1:3] == ["--kubeconfig", str(kubeconfig)] for c in commands)


def test_rate_evals_select_only_configured_idle_workers(monkeypatch):
    import launch_run
    import pod_rate_eval

    monkeypatch.setattr(launch_run, "load_guardrails", lambda: {
        "compute": {"gpu_pods": ["desktop-gpu", "second-desktop"]}})
    entries = [{"pod": "retired-cloud-gpu", "status": "RUNNING"},
               {"pod": "desktop-gpu", "status": "INTENT"}]
    assert pod_rate_eval.idle_pods(entries) == ["second-desktop"]


def test_operator_kick_uses_controller_credentials_not_worker_cluster(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    trace = tmp_path / "kubectl-args.json"
    kubectl = bindir / "kubectl"
    kubectl.write_text(f'#!{sys.executable}\nimport json, os, sys\n'
                       'from pathlib import Path\n'
                       'Path(os.environ["KUBECTL_TRACE"]).write_text(json.dumps(sys.argv[1:]))\n')
    kubectl.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("KUBECTL_TRACE", str(trace))
    monkeypatch.setenv("KUBECONFIG", str(tmp_path / "worker.yaml"))
    controller = str(tmp_path / "controller.yaml")
    monkeypatch.setenv("HEXAPOD_CONTROLLER_KUBECONFIG", controller)
    monkeypatch.setenv("HEXAPOD_REPO", str(tmp_path / "subject"))
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["bash", str(root / "orchestrator/ops.sh"), "cycle", "inspect Puget1"],
                   check=True, capture_output=True, timeout=5, env=os.environ.copy())
    args = json.loads(trace.read_text())
    assert args[:2] == ["--kubeconfig=" + controller, "--namespace=l2k"]
    assert args[2:7] == ["exec", "-i", "deploy/hexapod-controller", "-c", "controller"]
