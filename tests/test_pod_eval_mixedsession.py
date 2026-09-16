"""Auto-prestage trigger for the MIXED-SESSION gate (pod_eval.py).

2026-08-28 (standwalk unified1-mix gap): two independent triage
cycles found, by hand, that a "unified command-following" recipe
(env-native `goal.mode_seq>0`) needs `rl_move.sim.eval_mixed_session`
for its own pre-registered gate, but pod_eval's auto-prestage never
launched it (only `eval_checkpoint`/`eval_session` were wired in) —
both cycles worked around it manually via `ops.sh sessioncmd`. This
pins the pure trigger (`mode_seq_frac`) so the auto-launch this cycle
added can't silently regress to the same gap for the next arm in the
lineage.
"""
import importlib.util
import pathlib

_ORCH = pathlib.Path(__file__).resolve().parents[1] / "orchestrator"
_P = _ORCH / "pod_eval.py"
_spec = importlib.util.spec_from_file_location("pod_eval", _P)
pod_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pod_eval)

mode_seq_frac = pod_eval.mode_seq_frac


def test_no_mode_seq_key_is_zero():
    assert mode_seq_frac(["reward.foo=1", "control.hz=100"]) == 0.0


def test_mode_seq_present_reads_value():
    assert mode_seq_frac(["goal.mode_seq=0.75", "control.hz=100"]) == 0.75


def test_mode_seq_zero_value_does_not_trigger():
    # an explicit but disabled mode_seq (e.g. a respec that turns it
    # back off) must not fire the mixed-session auto-launch either.
    assert mode_seq_frac(["goal.mode_seq=0.0"]) == 0.0


def test_malformed_value_fails_safe_to_zero():
    assert mode_seq_frac(["goal.mode_seq=notanumber"]) == 0.0


def test_real_unified1_mix_cfg_stack_triggers():
    # abbreviated slice of the actual cw-standwalk-unified1-mix-s0
    # extra_args cfg-set list (order-sensitive keys omitted for
    # brevity — the function only cares about the one key).
    cfgs = ["env.model_source=mesh", "control.hz=100",
            "obs.mode_onehot=1", "goal.mode_seq=0.75",
            "goal.walk_cmd_mode=stress_mix"]
    assert mode_seq_frac(cfgs) > 0


# --- orphaned-remote-result reap (2026-08-28, found live on
# cw-standwalk-unified1-mix-{long-s0,long-s1}): the mixedsession
# auto-launch block only checked "already on controller"
# (session_verdict.json synced locally) and "still RUNNING remotely"
# — a pass that had ALREADY FINISHED remotely (session_verdict.json
# on the pod, process exited, nobody copied it back) fell through to
# "launch a new one", silently discarding a complete 90-episode
# result and re-running the whole dr0+owndr+dr0_long panel from
# scratch (confirmed live: both runs' `dr0` per-pass log had been
# freshly truncated back to just the model-load line while a complete
# session_verdict.json with all three passes sat right next to it).
# `remote_report_exists` now takes the completion filename so the
# mixedsession call site can reuse the same reap machinery gate/owncfg
# already got, keyed on `session_verdict.json` instead of
# `report.json`. ---
import types

remote_report_exists = pod_eval.remote_report_exists


def _fake_kexec(returncode):
    def _f(pod, cmd, timeout=60):
        return types.SimpleNamespace(returncode=returncode, stdout="",
                                      stderr="")
    return _f


def test_remote_report_exists_default_filename_is_report_json(monkeypatch):
    seen = {}

    def _f(pod, cmd, timeout=60):
        seen["cmd"] = cmd
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(pod_eval, "kexec", _f)
    remote_report_exists("some-pod", "logs/ckpt_eval/foo_gate")
    assert "logs/ckpt_eval/foo_gate/report.json" in seen["cmd"]


def test_remote_report_exists_custom_filename_for_mixedsession(monkeypatch):
    seen = {}

    def _f(pod, cmd, timeout=60):
        seen["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pod_eval, "kexec", _f)
    ok = remote_report_exists("some-pod", "logs/ckpt_eval/foo_mixedsession",
                               "session_verdict.json")
    assert ok is True
    assert ("logs/ckpt_eval/foo_mixedsession/session_verdict.json"
            in seen["cmd"])


def test_remote_report_exists_custom_filename_false_when_absent(monkeypatch):
    monkeypatch.setattr(pod_eval, "kexec", _fake_kexec(1))
    assert remote_report_exists(
        "some-pod", "logs/ckpt_eval/foo_mixedsession",
        "session_verdict.json") is False
