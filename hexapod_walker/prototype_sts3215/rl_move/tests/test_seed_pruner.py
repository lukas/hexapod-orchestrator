"""Tests for the mechanical seed pruner (operator order 2026-09-07 and
the 2026-09-07 PM safety repair).

Covers:
  * the pure decision rule (burn-in >= 25% of budget, 3 ADJACENT report
    windows entirely past burn-in, kill only on flat reward EMA AND
    non-improving behavior; immediate kill on collapse; never kill
    through a learning valley);
  * REAL window assembly from raw history rows -- the verified bugs:
    a 2,097,152-step 2M canary must NOT invent a 3M window, a 40M run
    at 15.1M must NOT invent 17.5M evidence, sparse buckets must NOT
    count as consecutive, observed step bounds are retained;
  * the kill path: revalidation pins the exact attempt (wandb_id,
    created, pod, trainer pid/start identity), kill-command failure and
    unconfirmed stops never write KILLED, budget-complete/deferred
    attempts are never killed, and the ledger update pins --created.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "orchestrator"))
import seed_pruner as sp                       # noqa: E402
from seed_pruner import (Window, decide, assemble_windows,  # noqa: E402
                         Decision)

BUDGET = 40_000_000
WIN = 2_500_000
# window grid: 2.5M each (budget/16); burn-in = 10M


def W(step, rew, v=0.05, ep=1900.0, fall=0.01, **kw):
    i = step // WIN - 1
    return Window(index=i, start=i * WIN, step=step,
                  obs_lo=i * WIN + 1, obs_hi=step - 1,
                  reward_ema=rew, v_along=v, ep_len=ep,
                  fall_rate=fall, **kw)


def flat_run(n=8, rew=1000.0, **kw):
    """n adjacent windows of fully stagnant reward+behavior."""
    return [W((i + 1) * WIN, rew, **kw) for i in range(n)]


# ---------------------------------------------------------------------------
# pure decision rule
# ---------------------------------------------------------------------------

def test_insufficient_windows_keep():
    d = decide(flat_run(2), BUDGET)
    assert d.action == "KEEP" and "insufficient windows" in d.reason


def test_burn_in_protection_keeps_early_stagnation():
    # 4 windows: the last 3 start at 2.5/5/7.5M, all before the 10M
    # burn-in -> protected.
    d = decide(flat_run(4), BUDGET)
    assert d.action == "KEEP" and "burn-in" in d.reason


def test_needs_three_windows_entirely_past_burn_in():
    # 6 windows: deciding 3 start at 7.5/10/12.5M; the 7.5M window
    # straddles the burn-in boundary -> still protected.
    d = decide(flat_run(6), BUDGET)
    assert d.action == "KEEP" and "burn-in" in d.reason


def test_post_burn_in_stagnation_kills():
    # 8 windows to 20M: deciding 3 start at 12.5/15/17.5M, all >= 10M
    # burn-in, reward EMA flat, no behavioral axis improving.
    d = decide(flat_run(8), BUDGET)
    assert d.action == "KILL"
    assert "stagnation" in d.reason


def test_reward_rising_vetoes_kill():
    ws = [W((i + 1) * WIN, 1000.0 + 20.0 * i) for i in range(8)]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP" and "valley veto" in d.reason


def test_behavior_improving_vetoes_kill_even_with_flat_reward():
    ws = [W((i + 1) * WIN, 1000.0, v=0.02 + 0.005 * i)
          for i in range(8)]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP" and "valley veto" in d.reason


def test_falls_decreasing_vetoes_kill():
    ws = [W((i + 1) * WIN, 1000.0, fall=max(0.0, 0.2 - 0.03 * i))
          for i in range(8)]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP"


def test_wrong_direction_collapse_kills_before_burn_in():
    # persistent wrong-way velocity fires with 3 adjacent windows even
    # at 7.5M (< 25% of 40M) -- immediate-kill class has no burn-in
    # protection.
    ws = [W((i + 1) * WIN, 1000.0, v=-0.03) for i in range(3)]
    d = decide(ws, BUDGET)
    assert d.action == "KILL_COLLAPSE"
    assert "wrong-direction" in d.reason


def test_wrong_direction_but_improving_is_kept():
    ws = [W(WIN, 1000.0, v=-0.05), W(2 * WIN, 1001.0, v=-0.03),
          W(3 * WIN, 1002.0, v=-0.01)]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP"


def test_rising_terminations_with_flat_reward_kills():
    ws = [W(WIN, 1000.0, fall=0.02), W(2 * WIN, 1000.0, fall=0.08),
          W(3 * WIN, 999.0, fall=0.20)]
    d = decide(ws, BUDGET)
    assert d.action == "KILL_COLLAPSE"
    assert "rising terminations" in d.reason


def test_rising_terminations_with_rising_reward_is_kept():
    ws = [W(WIN, 1000.0, fall=0.02), W(2 * WIN, 1100.0, fall=0.08),
          W(3 * WIN, 1250.0, fall=0.20)]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP"


def test_small_fall_rate_noise_does_not_collapse_kill():
    ws = flat_run(8)
    ws[-3] = W(6 * WIN, 1000.0, fall=0.01)
    ws[-2] = W(7 * WIN, 1000.0, fall=0.02)
    ws[-1] = W(8 * WIN, 1000.0, fall=0.03)
    d = decide(ws, BUDGET)
    assert d.action != "KILL_COLLAPSE"


def test_never_prune_on_reward_alone():
    ws = [Window(index=i, start=i * WIN, step=(i + 1) * WIN,
                 obs_lo=i * WIN + 1, obs_hi=(i + 1) * WIN - 1,
                 reward_ema=1000.0)
          for i in range(8)]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP" and "reward alone" in d.reason


def test_missing_behavior_series_in_tail_keeps():
    ws = flat_run(8)
    ws[-1] = Window(index=7, start=7 * WIN, step=8 * WIN,
                    obs_lo=7 * WIN + 1, obs_hi=8 * WIN - 1,
                    reward_ema=1000.0)  # no behavior row
    d = decide(ws, BUDGET)
    assert d.action == "KEEP"


# ---------------------------------------------------------------------------
# 2026-09-07 PM repair: adjacency / budget-complete / burn-in geometry
# ---------------------------------------------------------------------------

def test_sparse_windows_are_not_consecutive_evidence():
    # verified bug: buckets 12.5M / 20M / 32.5M were accepted as "3
    # consecutive windows". Indices 4 / 7 / 12 are NOT adjacent -> KEEP.
    ws = []
    for i in (4, 7, 12):
        ws.append(Window(index=i, start=i * WIN, step=(i + 1) * WIN,
                         obs_lo=i * WIN + 1, obs_hi=(i + 1) * WIN - 1,
                         reward_ema=1000.0, v_along=0.05, ep_len=1900.0,
                         fall_rate=0.01))
    d = decide(ws, BUDGET)
    assert d.action == "KEEP" and "not adjacent" in d.reason


def test_sparse_windows_never_collapse_kill_either():
    ws = []
    for i in (4, 7, 12):
        ws.append(Window(index=i, start=i * WIN, step=(i + 1) * WIN,
                         obs_lo=i * WIN + 1, obs_hi=(i + 1) * WIN - 1,
                         reward_ema=1000.0, v_along=-0.05, ep_len=1900.0,
                         fall_rate=0.01))
    d = decide(ws, BUDGET)
    assert d.action == "KEEP" and "not adjacent" in d.reason


def test_budget_complete_run_is_never_killed():
    # verified live incident: a run that consumed its whole 40M budget
    # (obs past 40M) was slope-killed on an invented 42.5M window. With
    # honest windows, observed steps >= budget must always KEEP.
    ws = flat_run(16)
    ws[-1].obs_hi = 40_370_176     # durable completion evidence
    d = decide(ws, BUDGET)
    assert d.action == "KEEP" and "budget complete" in d.reason


def test_unknown_index_refuses_to_judge():
    ws = flat_run(8)
    ws[-2].index = -1              # uncertain grid position
    d = decide(ws, BUDGET)
    assert d.action == "KEEP"


# ---------------------------------------------------------------------------
# real window assembly (verified reproductions)
# ---------------------------------------------------------------------------

def _rows(key, lo, hi, every, val=1000.0):
    return [{"global_step": s, key: val}
            for s in range(lo, hi + 1, every)]


def test_assembly_2m_canary_does_not_invent_third_window():
    # verified bug: an actual 2,097,152-step 2M canary produced windows
    # 1M/2M/3M (the 3M one from overflow rows) and then KILLed. The
    # partial third window must be excluded -> only 2 windows -> KEEP.
    rew = _rows("rollout/ep_rew_mean", 8192, 2_097_152, 32_768)
    ws = assemble_windows(2_000_000, rew)
    assert [w.step for w in ws] == [1_000_000, 2_000_000]
    assert max(w.obs_hi for w in ws) <= 2_097_152
    d = decide(ws, 2_000_000)
    assert d.action == "KEEP" and "insufficient" in d.reason


def test_assembly_40m_at_15m_does_not_invent_future_window():
    # verified bug: a 40M run at 15.1M steps invented a 17.5M
    # "last window". The 15M..17.5M bucket is partial -> excluded.
    rew = _rows("rollout/ep_rew_mean", 50_000, 15_100_000, 50_000)
    ws = assemble_windows(BUDGET, rew)
    assert ws[-1].step == 15_000_000 and ws[-1].index == 5
    assert all(w.obs_hi <= 15_100_000 for w in ws)
    assert all(w.obs_lo >= 0 for w in ws)


def test_assembly_retains_actual_observed_bounds():
    rew = _rows("rollout/ep_rew_mean", 100_000, 7_400_000, 100_000)
    ws = assemble_windows(BUDGET, rew)
    # bucket 0 spans 0..2.5M; first observation was at 100k
    assert ws[0].obs_lo == 100_000
    assert ws[0].obs_hi == 2_400_000
    assert ws[-1].step == 5_000_000  # 5M..7.5M bucket partial (7.4M obs)


def test_assembly_no_reward_rows_returns_nothing():
    assert assemble_windows(BUDGET, []) == []
    assert assemble_windows(
        BUDGET, [{"global_step": None, "rollout/ep_rew_mean": 1.0}]) == []


def test_assembly_sparse_reward_gaps_yield_nonadjacent_windows():
    # reward logging gap: data in buckets 0-2 then bucket 6 only
    rew = (_rows("rollout/ep_rew_mean", 50_000, 7_400_000, 50_000)
           + _rows("rollout/ep_rew_mean", 15_050_000, 17_600_000, 50_000))
    ws = assemble_windows(BUDGET, rew)
    assert [w.index for w in ws] == [0, 1, 2, 6]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP" and "not adjacent" in d.reason


# ---------------------------------------------------------------------------
# kill path: pinning, revalidation, failed kills, concurrent attempts
# ---------------------------------------------------------------------------

PIN = {"run": "cw-test-run", "created": "2026-09-07T10:00:00+00:00",
       "wandb_id": "abc123", "pod": "hexapod-mjx-train-9",
       "status": "RUNNING"}
DEC = Decision("KILL", "test stagnation", {"why": "test"})


class _KillEnv:
    """Monkeypatched happy-path kill environment; tests break one leg."""

    def __init__(self, monkeypatch):
        self.marked: list[tuple] = []
        self.killed_pairs: list = []
        monkeypatch.setattr(sp, "_reload_entry",
                            lambda run, created: dict(PIN))
        monkeypatch.setattr(sp, "_wandb_state_steps",
                            lambda entry: ("running", 20_000_000))
        monkeypatch.setattr(sp, "_handoff_phase", lambda pod, run: None)
        monkeypatch.setattr(sp, "_pin_procs",
                            lambda pod, run: [(4242, 987654)])
        monkeypatch.setattr(sp, "_kill_procs", self._kill_procs)
        monkeypatch.setattr(sp, "_procs_alive", lambda pod, run: False)
        monkeypatch.setattr(sp, "_mark_killed", self._mark_killed)
        monkeypatch.setattr(sp.time, "sleep", lambda s: None)

    def _kill_procs(self, pod, run, pairs):
        self.killed_pairs.append(pairs)
        return True, [p for p, _ in pairs], []

    def _mark_killed(self, run, created, verdict):
        self.marked.append((run, created, verdict))
        return True


def test_kill_happy_path_pins_created_and_confirms(monkeypatch):
    env = _KillEnv(monkeypatch)
    assert sp._kill(dict(PIN), DEC, BUDGET) is True
    assert len(env.marked) == 1
    run, created, verdict = env.marked[0]
    assert run == PIN["run"] and created == PIN["created"]
    assert "4242:987654" in verdict          # pinned trainer identity
    assert "stop confirmed" in verdict


def test_kill_command_failure_never_writes_killed(monkeypatch):
    env = _KillEnv(monkeypatch)
    monkeypatch.setattr(sp, "_kill_procs",
                        lambda pod, run, pairs: (False, [], [4242]))
    assert sp._kill(dict(PIN), DEC, BUDGET) is False
    assert env.marked == []


def test_unconfirmed_stop_never_writes_killed(monkeypatch):
    env = _KillEnv(monkeypatch)
    monkeypatch.setattr(sp, "_procs_alive", lambda pod, run: True)
    assert sp._kill(dict(PIN), DEC, BUDGET) is False
    assert env.marked == []


def test_unverifiable_stop_never_writes_killed(monkeypatch):
    env = _KillEnv(monkeypatch)
    monkeypatch.setattr(sp, "_procs_alive", lambda pod, run: None)
    assert sp._kill(dict(PIN), DEC, BUDGET) is False
    assert env.marked == []


def test_no_live_trainer_never_writes_killed(monkeypatch):
    env = _KillEnv(monkeypatch)
    monkeypatch.setattr(sp, "_pin_procs", lambda pod, run: [])
    assert sp._kill(dict(PIN), DEC, BUDGET) is False
    assert env.marked == []


def test_proc_scan_failure_aborts(monkeypatch):
    env = _KillEnv(monkeypatch)
    monkeypatch.setattr(sp, "_pin_procs", lambda pod, run: None)
    assert sp._kill(dict(PIN), DEC, BUDGET) is False
    assert env.marked == []


def test_concurrent_attempt_swap_aborts(monkeypatch):
    # verified hazard: a same-name relaunch lands between audit and kill;
    # the fresh ledger row carries a different wandb_id -> abort.
    env = _KillEnv(monkeypatch)
    swapped = dict(PIN, wandb_id="zzz999")
    monkeypatch.setattr(sp, "_reload_entry",
                        lambda run, created: swapped)
    assert sp._kill(dict(PIN), DEC, BUDGET) is False
    assert env.marked == []


def test_attempt_vanished_from_ledger_aborts(monkeypatch):
    env = _KillEnv(monkeypatch)
    monkeypatch.setattr(sp, "_reload_entry", lambda run, created: None)
    assert sp._kill(dict(PIN), DEC, BUDGET) is False
    assert env.marked == []


def test_attempt_no_longer_running_aborts(monkeypatch):
    env = _KillEnv(monkeypatch)
    fin = dict(PIN, status="FINISHED")
    monkeypatch.setattr(sp, "_reload_entry", lambda run, created: fin)
    assert sp._kill(dict(PIN), DEC, BUDGET) is False
    assert env.marked == []


def test_budget_complete_at_revalidation_aborts(monkeypatch):
    # verified live incident class: run completed its whole budget but
    # ledger/W&B still said RUNNING at audit time.
    env = _KillEnv(monkeypatch)
    monkeypatch.setattr(sp, "_wandb_state_steps",
                        lambda entry: ("running", 40_370_176))
    assert sp._kill(dict(PIN), DEC, BUDGET) is False
    assert env.marked == []


def test_wandb_finished_at_revalidation_aborts(monkeypatch):
    env = _KillEnv(monkeypatch)
    monkeypatch.setattr(sp, "_wandb_state_steps",
                        lambda entry: ("finished", 20_000_000))
    assert sp._kill(dict(PIN), DEC, BUDGET) is False
    assert env.marked == []


def test_deferred_artifacts_phase_aborts(monkeypatch):
    # GPU training over; CPU finalizer delivering artifacts -> never kill.
    env = _KillEnv(monkeypatch)
    monkeypatch.setattr(sp, "_handoff_phase",
                        lambda pod, run: "artifacts_pending")
    assert sp._kill(dict(PIN), DEC, BUDGET) is False
    assert env.marked == []


def test_unreadable_handoff_registry_aborts(monkeypatch):
    env = _KillEnv(monkeypatch)
    monkeypatch.setattr(sp, "_handoff_phase", lambda pod, run: "ERROR")
    assert sp._kill(dict(PIN), DEC, BUDGET) is False
    assert env.marked == []


def test_wandb_identity_mismatch_raises_and_is_skipped():
    class FakeRun:
        name = "some-other-run"
        state = "running"
        summary = {}

    class FakeApi:
        def run(self, path):
            assert path.endswith("/abc123")  # fetch by id, not name
            return FakeRun()

    import types
    fake_wandb = types.SimpleNamespace(Api=FakeApi)
    real = sys.modules.get("wandb")
    sys.modules["wandb"] = fake_wandb
    try:
        try:
            sp._wandb_run_by_id(dict(PIN))
            raised = False
        except sp.AttemptIdentityError:
            raised = True
        assert raised
    finally:
        if real is not None:
            sys.modules["wandb"] = real
        else:
            del sys.modules["wandb"]
