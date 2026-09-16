"""find_checkpoint must try the ledger's own --out-name before guessing
from the run name.

2026-09-10 (decleg-sde-s0-acq1r2 triage): a hand-relaunched retry keeps
the ORIGINAL --out-name so the checkpoint lands under the intended
lineage name (e.g. "..._acq1"), not the retry run's own name (e.g.
"..-acq1r2"). `find_checkpoint` used to guess ONLY from the run name
and reported a false "no checkpoint ... nothing to eval" even though
the checkpoint existed under its recorded out-name. Pin the fix with
subprocess I/O mocked (no real pod).
"""
import importlib.util
import pathlib
import types

_ORCH = pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
_P = _ORCH / "pod_eval.py"
_spec = importlib.util.spec_from_file_location("pod_eval_outname", _P)
pod_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pod_eval)


def _fake_kexec_only_matches(good_path):
    def _f(pod, cmd, timeout=60):
        rc = 0 if f"test -s {good_path}" in cmd else 1
        return types.SimpleNamespace(returncode=rc, stdout="", stderr="")
    return _f


def test_out_name_checkpoint_found_before_run_name_guess(monkeypatch):
    # The checkpoint sits at the out-name path; the run-name-derived
    # guess would never exist on the pod.
    good = (f"{pod_eval.POD_PROTO}/rl_move/sim/policies/"
            "ppo_goal_cw_walkscratch_easy0905_decleg_sde_s0_acq1.zip")
    monkeypatch.setattr(pod_eval, "kexec", _fake_kexec_only_matches(good))
    got = pod_eval.find_checkpoint(
        "some-pod", "cw-walkscratch-easy0905-decleg-sde-s0-acq1r2",
        "joint_walk",
        out_name="ppo_goal_cw_walkscratch_easy0905_decleg_sde_s0_acq1")
    assert got == good


def test_out_name_tried_first_in_candidate_order():
    names_seen = []

    def _record_kexec(pod, cmd, timeout=60):
        names_seen.append(cmd)
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")

    import pod_eval as _reimport  # noqa: F401 - keep module identity simple
    pod_eval.kexec = _record_kexec
    pod_eval.push_local = lambda pod, name: None
    pod_eval.find_checkpoint("some-pod", "myrun", "joint_walk",
                              out_name="ppo_goal_myrun_custom")
    assert names_seen, "kexec never called"
    assert "ppo_goal_myrun_custom.zip" in names_seen[0]


def test_no_out_name_falls_back_to_run_name_guess(monkeypatch):
    # Backward compatible: omitting out_name behaves exactly as before.
    good = (f"{pod_eval.POD_PROTO}/rl_move/sim/policies/"
            "ppo_goal_myplainrun.zip")
    monkeypatch.setattr(pod_eval, "kexec", _fake_kexec_only_matches(good))
    got = pod_eval.find_checkpoint("some-pod", "myplainrun", "joint_walk")
    assert got == good
