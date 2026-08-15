"""pod_trainers()'s cmdline-scan glob (2026-08-15 dynrep triage fix).

The launcher's own pre-launch free-pod check and dedupe guard (not just
capacity.py's report) call `pod_trainers()` to decide whether a pod is
busy. The scan is a shell `case` glob run on the pod via kexec; this
test exercises the REAL glob/case logic (via `_TRAINER_SCAN_SCRIPT`,
parameterized on `{proc}`) against a fabricated /proc-like directory
tree, so the pattern can't silently drift from what actually runs on a
pod without a test failing — no live pod touched.

Regression: `rl_move.dynamics.train_ppo_transfer` (the condition A/B/C
PPO-transfer cohorts, e.g. risewalk-single2 / futurewalk-C) was NOT
matched — only the exact `rl_move.dynamics.train ` (no trailing
underscore) module was. capacity.py and the launcher's own busy check
read those pods as free while genuinely running a trainer.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
import launch_run as lr  # noqa: E402


def _fake_proc(tmp_path, pid: int, argv: list[str]) -> None:
    d = tmp_path / str(pid)
    d.mkdir()
    (d / "cmdline").write_bytes(("\0".join(argv) + "\0").encode())


def _scan(tmp_path) -> list[str]:
    script = lr._TRAINER_SCAN_SCRIPT.format(proc=str(tmp_path))
    out = subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, timeout=10, check=True).stdout
    return out.splitlines()


def test_matches_every_trainer_module(tmp_path):
    _fake_proc(tmp_path, 1, ["python3", "-m", "rl_move.sim.train_ppo_mjx",
                             "--run-name", "cw-foo"])
    _fake_proc(tmp_path, 2, ["python3", "-m", "rl_move.dynamics.train",
                             "--name", "cw-dyn-foo"])
    _fake_proc(tmp_path, 3, ["python3", "-m", "rl_move.dynamics.fresh_pipeline",
                             "--name", "cw-fresh-foo"])
    # The regression this test guards: train_ppo_transfer must match too.
    _fake_proc(tmp_path, 4, ["python3", "-m", "rl_move.dynamics.train_ppo_transfer",
                             "--condition", "B", "--task", "rise", "--seed", "5",
                             "--name", "rw_rise_B_s5"])
    lines = _scan(tmp_path)
    assert len(lines) == 4, lines
    joined = "\n".join(lines)
    for needle in ("train_ppo_mjx", "dynamics.train --name", "fresh_pipeline",
                   "train_ppo_transfer"):
        assert needle in joined, (needle, joined)


def test_excludes_forkworker_and_cycle_agent_and_similar_names(tmp_path):
    # forkserver/spawn workers: -c cmdline, must be excluded.
    _fake_proc(tmp_path, 10, ["python3", "-c", "import multiprocessing..."])
    # A cycle-agent process whose cmdline happens to embed the standing
    # prompt text "train_ppo" must NOT match (2026-08-09 c37 lesson).
    _fake_proc(tmp_path, 11, ["claude-agent", "some prompt mentioning "
                             "rl_move.sim.train_ppo_mjx in prose"])
    # A module name that merely STARTS WITH the same prefix but isn't
    # one of the real trainer modules must not false-positive.
    _fake_proc(tmp_path, 12, ["python3", "-m",
                             "rl_move.dynamics.train_ppo_transfer_test_helper"])
    lines = _scan(tmp_path)
    assert lines == [], lines


def test_pod_trainers_extracts_name_from_transfer_cmdline(monkeypatch):
    monkeypatch.setattr(
        lr, "kexec",
        lambda pod, script, timeout=60: (
            "python3 -m rl_move.dynamics.train_ppo_transfer --condition B "
            "--task rise --seed 5 --name rw_rise_B_s5"
        ),
    )
    assert lr.pod_trainers("hexapod-mjx-train-4") == ["rw_rise_B_s5"]
