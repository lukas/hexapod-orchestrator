"""Tests for the mechanical seed pruner's pure decision rule
(operator order 2026-09-07: burn-in >= 25% of budget, 3 consecutive
report windows, kill only on flat reward EMA AND non-improving
behavior; immediate kill on collapse/exploit; never kill through a
learning valley)."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "orchestrator"))
from seed_pruner import Window, decide  # noqa: E402

BUDGET = 40_000_000
# window grid: 2.5M each (budget/16); burn-in = 10M


def W(step, rew, v=0.05, ep=1900.0, fall=0.01, **kw):
    return Window(step=step, reward_ema=rew, v_along=v, ep_len=ep,
                  fall_rate=fall, **kw)


def flat_run(n=8, rew=1000.0, **kw):
    """n windows of fully stagnant reward+behavior ending at n*2.5M."""
    return [W((i + 1) * 2_500_000, rew, **kw) for i in range(n)]


def test_insufficient_windows_keep():
    d = decide(flat_run(2), BUDGET)
    assert d.action == "KEEP" and "insufficient windows" in d.reason


def test_burn_in_protection_keeps_early_stagnation():
    # 4 windows but all before/straddling the 10M burn-in: last window
    # ends at 10M -> zero fully-post-burn-in windows.
    d = decide(flat_run(4), BUDGET)
    assert d.action == "KEEP" and "burn-in" in d.reason


def test_needs_three_post_burn_in_windows():
    # windows end at 12.5M and 15M -> only 2 post-burn-in windows
    d = decide(flat_run(6), BUDGET)
    assert d.action == "KEEP" and "burn-in" in d.reason


def test_post_burn_in_stagnation_kills():
    # 8 windows to 20M: last 3 (12.5/15/17.5/20M...) all past 10M,
    # reward EMA flat, no behavioral axis improving.
    d = decide(flat_run(8), BUDGET)
    assert d.action == "KILL"
    assert "stagnation" in d.reason


def test_reward_rising_vetoes_kill():
    ws = [W((i + 1) * 2_500_000, 1000.0 + 20.0 * i) for i in range(8)]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP" and "valley veto" in d.reason


def test_behavior_improving_vetoes_kill_even_with_flat_reward():
    # reward flat, but velocity along command improving
    ws = [W((i + 1) * 2_500_000, 1000.0, v=0.02 + 0.005 * i)
          for i in range(8)]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP" and "valley veto" in d.reason


def test_falls_decreasing_vetoes_kill():
    ws = [W((i + 1) * 2_500_000, 1000.0, fall=max(0.0, 0.2 - 0.03 * i))
          for i in range(8)]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP"


def test_wrong_direction_collapse_kills_before_burn_in():
    # persistent wrong-way velocity fires with 3 windows even at 7.5M
    # (< 25% of 40M) -- immediate-kill class has no burn-in protection.
    ws = [W((i + 1) * 2_500_000, 1000.0, v=-0.03) for i in range(3)]
    d = decide(ws, BUDGET)
    assert d.action == "KILL_COLLAPSE"
    assert "wrong-direction" in d.reason


def test_wrong_direction_but_improving_is_kept():
    # still negative but clearly improving toward zero -> learning, keep
    ws = [W(2_500_000, 1000.0, v=-0.05), W(5_000_000, 1001.0, v=-0.03),
          W(7_500_000, 1002.0, v=-0.01)]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP"


def test_rising_terminations_with_flat_reward_kills():
    ws = [W(2_500_000, 1000.0, fall=0.02), W(5_000_000, 1000.0, fall=0.08),
          W(7_500_000, 999.0, fall=0.20)]
    d = decide(ws, BUDGET)
    assert d.action == "KILL_COLLAPSE"
    assert "rising terminations" in d.reason


def test_rising_terminations_with_rising_reward_is_kept():
    # a valley: terminations up but reward clearly climbing -> keep
    ws = [W(2_500_000, 1000.0, fall=0.02), W(5_000_000, 1100.0, fall=0.08),
          W(7_500_000, 1250.0, fall=0.20)]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP"


def test_small_fall_rate_noise_does_not_collapse_kill():
    # rising but tiny (below collapse_min_fall_rate) -> not a collapse
    ws = flat_run(8)
    ws[-3] = W(15_000_000, 1000.0, fall=0.01)
    ws[-2] = W(17_500_000, 1000.0, fall=0.02)
    ws[-1] = W(20_000_000, 1000.0, fall=0.03)
    d = decide(ws, BUDGET)
    # falls regressing + flat reward post-burn-in -> slope KILL is fine,
    # but it must NOT be labeled a collapse
    assert d.action != "KILL_COLLAPSE"


def test_never_prune_on_reward_alone():
    ws = [Window(step=(i + 1) * 2_500_000, reward_ema=1000.0)
          for i in range(8)]
    d = decide(ws, BUDGET)
    assert d.action == "KEEP" and "reward alone" in d.reason


def test_canary_budget_never_slope_killed():
    # 2M canary: windows are 1M wide (MIN_WINDOW_STEPS floor) -> at most
    # 2 windows exist; the slope rule can never fire.
    ws = [W(1_000_000, 500.0), W(2_000_000, 500.0)]
    d = decide(ws, 2_000_000)
    assert d.action == "KEEP"


def test_missing_behavior_series_in_tail_keeps():
    ws = flat_run(8)
    ws[-1] = Window(step=20_000_000, reward_ema=1000.0)  # no behavior row
    d = decide(ws, BUDGET)
    assert d.action == "KEEP"
