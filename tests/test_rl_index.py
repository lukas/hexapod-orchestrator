"""rl_index: canonical outcomes, lineage, sim->real joins, build output."""
from __future__ import annotations

import json

import pytest

import rl_index
import state_dir


# ------------------------------------------------------------ outcome()
@pytest.mark.parametrize("status,phase,verdict,expected", [
    ("PASS", "acquisition", "PASS -- all clauses clear", "PASS"),
    ("ACQ PASS", "acquisition", None, "PASS"),
    ("HARDENING PASS", "hardening", None, "PASS"),
    ("PASSED", None, None, "PASS"),
    ("PASS (partial)", None, None, "PARTIAL"),
    ("ACQ PARTIAL - MATCHED-DRIFT CONFIRMED", None, None, "PARTIAL"),
    ("FAIL", "acquisition", "FAIL: gait destroyed", "FAIL"),
    ("ACQ FAIL (misaligned)", None, None, "INVALID"),
    ("FAIL - INFORMATIVE (negative control CONFIRMS)", None, None, "FAIL"),
    ("FINISHED_FAIL", None, None, "FAIL"),
    ("DISCOVERY MISS (near, informative)", None, None, "FAIL"),
    ("CANARY FAIL - MECHANISM", "canary", None, "CANARY_FAIL"),
    ("CANARY_FAIL_MECHANISM", "canary", None, "CANARY_FAIL"),
    ("FAIL-MECHANISM", "canary", None, "CANARY_FAIL"),
    ("CANARY FAIL - INFRASTRUCTURE", "canary", None, "CANARY_FAIL_INFRA"),
    ("CANARY PASS", "canary", None, "CANARY_PASS"),
    ("CANARY_PASS_CONTINUE", "canary", None, "CANARY_PASS"),
    ("canary_fail", "canary", None, "CANARY_FAIL"),
    ("CONTINUE", "acquisition", None, "CONTINUE"),
    ("ACQ CONTINUE - gate not yet met", None, None, "CONTINUE"),
    ("INFORMATIVE", None, None, "INFORMATIVE"),
    ("NO-EFFECT", None, None, "INFORMATIVE"),
    ("FLAT-REGRESSED", None, None, "INFORMATIVE"),
    ("INVALID", None, None, "INVALID"),
    ("INCONCLUSIVE - CONTROL DRIFT", None, None, "INVALID"),
    ("REFUSED", None, None, "REFUSED"),
    ("RUNNING", None, None, "RUNNING"),
    ("INTENT", None, None, "INTENT"),
    ("FAILED", None, None, "CRASHED"),
    ("LAUNCH_CRASH", None, None, "CRASHED"),
    ("FAILED_BUG", None, None, "CRASHED"),
    ("KILLED", None, None, "KILLED"),
    ("KILLED_BY_OPERATOR", None, None, "KILLED"),
    ("SELF_KILLED_OVER_CAP", None, None, "KILLED"),
    ("STOPPED_SUPERSEDED", None, None, "KILLED"),
    ("SUPERSEDED", None, None, "SUPERSEDED"),
    ("STALE_DUPLICATE", None, None, "SUPERSEDED"),
    ("RECONSTRUCTED_LEDGER_ENTRY", None, None, "SUPERSEDED"),
    ("FINISHED", None, None, "UNVERDICTED"),
    ("DONE", None, "", "UNVERDICTED"),
    ("FINISHED", None, "PASS. Harness 6/6 ...", "PASS"),
    ("FINISHED", None, "FAIL (round 8): sto walk 2/6", "FAIL"),
    ("FINISHED", None, "CANARY PASS (mechanism healthy)", "CANARY_PASS"),
    ("FINISHED", None, "Launch failure (gotcha 13b EOFError)", "CRASHED"),
    ("FINISHED", None, "IMPORT-ERA STUB (2026-08-09 shadow-ledger)", "SUPERSEDED"),
    ("FINISHED", None, "DIAGNOSTIC ANSWERED: FALSE branch", "VERDICTED"),
    ("done", None, "Scratch control, matched triple at 2M steps.", "VERDICTED"),
])
def test_outcome_vocabulary(status, phase, verdict, expected):
    entry = {"run": "x", "status": status}
    if phase:
        entry["phase"] = phase
    if verdict is not None:
        entry["verdict"] = verdict
    assert rl_index.outcome(entry) == expected


def test_every_outcome_is_documented():
    for e in [{"status": s} for s in ("PASS", "FAIL", "REFUSED", "RUNNING", "FINISHED",
                                       "KILLED", "FAILED", "SUPERSEDED", "INVALID",
                                       "INFORMATIVE", "PARTIAL", "CONTINUE", "INTENT")]:
        assert rl_index.outcome(e) in rl_index.OUTCOMES


@pytest.mark.parametrize("raw,expected", [
    (True, True), (False, False), ("yes", True), ("no", False), ("True", True),
    ("False", False), (None, None), ("maybe", None), ("", None),
])
def test_coerce_hardware_ready(raw, expected):
    assert rl_index.coerce_hardware_ready(raw) is expected


# ------------------------------------------------------------ ledger rows
def _entry(run, minute, **kw):
    e = {"run": run, "status": "PASS", "track": "walkcurr", "phase": "acquisition",
         "created": f"2026-09-01T10:{minute:02d}:00+00:00", "steps": 2_000_000,
         "extra_args": ["--task", "joint_walk", "--seed", "0",
                        "--cfg-set", "reward.k_walk=1.0", "--cfg-set", "dr.mass_scale=0.9,1.1"]}
    e.update(kw)
    return e


LEDGER = [
    _entry("cw-root", 0, parent="ppo_goal_cw_old_champion.zip", status="CANARY PASS", phase="canary"),
    _entry("cw-root-acq", 1, parent="cw-root",
           extra_args=["--task", "joint_walk", "--seed", "0", "--init-from", "x.zip",
                       "--cfg-set", "reward.k_walk=2.0", "--cfg-set", "dr.mass_scale=0.9,1.1",
                       "--cfg-set", "goal.new_key=1", "--notes", "long essay"],
           verdict="PASS -- clears the gate", hardware_ready="yes"),
    _entry("cw-root-acq-s1", 2, parent="ppo_goal_cw_root_acq.zip", status="ACQ FAIL",
           verdict="FAIL: leg 4 sacrificed", hardware_ready=False),
    # a stale REFUSED duplicate attempt must not replace the run above
    _entry("cw-root-acq-s1", 3, status="REFUSED", refused_reason="busy pod"),
    _entry("cw-other", 4, track="speed", status="FINISHED", verdict=None),
]


def test_load_runs_lineage_and_fields(state_ledger):
    state_ledger(LEDGER)
    runs = rl_index.load_runs()
    assert set(runs) == {"cw-root", "cw-root-acq", "cw-root-acq-s1", "cw-other"}
    acq = runs["cw-root-acq"]
    assert acq["parent"] == "cw-root" and acq["root"] == "cw-root"
    assert acq["outcome"] == "PASS" and acq["hardware_ready"] is True
    assert acq["children"] == ["cw-root-acq-s1"]
    # parent given as a checkpoint path resolves to the run by stem
    s1 = runs["cw-root-acq-s1"]
    assert s1["parent"] == "cw-root-acq" and s1["ancestors"] == ["cw-root-acq", "cw-root"]
    assert s1["outcome"] == "FAIL" and s1["status"] == "ACQ FAIL"   # REFUSED dup ignored
    root = runs["cw-root"]
    assert root["parent"] is None and root["parent_raw"] == "ppo_goal_cw_old_champion.zip"
    assert runs["cw-other"]["outcome"] == "UNVERDICTED"


def test_story_diff_vs_parent_skips_bookkeeping_flags(state_ledger):
    state_ledger(LEDGER)
    runs = rl_index.load_runs()
    s = rl_index.story("cw-root-acq", runs, state_dir.load_ledger(), {}, [], [])
    d = s["diff_vs_parent"]
    assert d["cfg_changed"] == {"reward.k_walk": ["1.0", "2.0"], "goal.new_key": [None, "1"]}
    assert d["cfg_dropped"] == {}
    assert "--init-from" in d["flags_changed"] and "--notes" not in d["flags_changed"]
    md = rl_index.story_md(s)
    assert "cfg reward.k_walk: 1.0 -> 2.0" in md and "long essay" not in md
    assert "## Lineage" in md and "cw-root — CANARY_PASS" in md


# ------------------------------------------------------------ sim -> real join
def _policy_file(path, source, notes=""):
    path.write_text(json.dumps({"meta": {"source": source, "name": path.stem, "obs_dim": 72,
                                         "architecture": "mlp", "training_hz": 50.0,
                                         "notes": notes},
                                "W1": [[0.0]], "b1": [0.0]}))


def _lab_session(root, sid, robot, policy, legs):
    d = root / sid
    d.mkdir(parents=True)
    (d / "session.json").write_text(json.dumps({"id": sid, "robot": robot, "agent": "endurance.py",
                                                "purpose": f"endurance {policy}",
                                                "created_iso": "2026-09-20T12:00:00-0700"}))
    (d / "walk_summary.json").write_text(json.dumps({"robot": robot, "legs": [
        {"label": f"leg{i}", "mode": f"RL:{policy}", "policy": policy, "seconds": 6.0,
         "commanded_speed_mm_s": 100.0, "straight_speed_mm_s": v, "speed_ratio": v / 100.0,
         "mean_speed_mm_s": v + 5, "tilt_max_deg": 8.0, "heading_change_deg": -3.0,
         "stop_reason": "time", "cmd_v": [100.0, 0.0, 0.0]} for i, v in enumerate(legs)]
        + [{"label": "scripted", "mode": "J", "seconds": 4.0, "speed_ratio": 0.5}]}))


def test_policies_join_runs_and_real_walks(state_ledger, tmp_path, monkeypatch):
    state_ledger(LEDGER)
    proto = tmp_path / "proto"
    (proto / "linux_control" / "policies").mkdir(parents=True)
    _policy_file(proto / "linux_control" / "policies" / "acq_50hz.json",
                 "rl_move/sim/policies/ppo_goal_cw_root_acq.zip", "exported for hexapod2")
    (proto / "rl_docs" / "tracks" / "walkcurr" / "bundle_v1").mkdir(parents=True)
    (proto / "rl_docs" / "tracks" / "walkcurr" / "bundle_v1" / "transfer_manifest.json").write_text(
        json.dumps({"candidate_name": "cand-v1", "parent_goal": "rl_only", "components": [
            {"controller": "rl_move/sim/policies/ppo_goal_cw_root_acq.zip",
             "exported_np_policy": "linux_control/policies/acq_50hz.json"}]}))
    lab = tmp_path / "lab_runs"
    _lab_session(lab, "s-1", "hexapod2", "acq_50hz.json", [30.0, 40.0, 50.0])
    _lab_session(lab, "s-2", "hexapod2", "acq_50hz.json", [20.0])
    mirror = tmp_path / "registry"
    _lab_session(mirror, "s-1", "hexapod2", "acq_50hz.json", [30.0, 40.0, 50.0])  # same id: deduped
    _lab_session(lab, "s-3", "hexapod2", "unknown_policy.json", [10.0])
    monkeypatch.setattr(rl_index, "LAB_RUNS_DIRS", (lab, mirror, tmp_path / "missing"))
    monkeypatch.setattr(rl_index, "LAB2_DB", tmp_path / "no.sqlite3")

    runs = rl_index.load_runs()
    robot_lists = {"hexapod2": [{"file": "acq_50hz.json", "source": "ppo_goal_cw_root_acq.zip",
                                 "active": True},
                                {"file": "s1_50hz.json", "source": "ppo_goal_cw_root_acq_s1.zip",
                                 "notes": "uploaded only"}]}
    pols = rl_index.load_policies(proto, runs, robot_lists)
    assert pols["acq_50hz.json"]["run"] == "cw-root-acq"
    assert pols["acq_50hz.json"]["on_robots"] == ["hexapod2 (active)"]
    assert pols["acq_50hz.json"]["manifests"][0]["candidate"] == "cand-v1"
    # a file that exists only on the robot still resolves through its source stem
    assert pols["s1_50hz.json"]["run"] == "cw-root-acq-s1"

    rows = rl_index.load_real_walks()
    assert len(rows) == 5                      # 3 + 1 (+0 dedup) + 1 unknown; scripted skipped
    agg = rl_index.summarise_real(rows)
    a = agg["acq_50hz.json"]
    assert a["legs"] == 4 and a["sessions"] == 2 and a["speed_ratio_med"] == 0.35
    assert a["robots"] == ["hexapod2"]

    for name, ag in agg.items():
        pols.setdefault(name, rl_index._blank_policy(name))["real"] = ag
    prom = rl_index.promising(runs, pols, agg)
    walked = [w["policy"] for w in prom["walked_on_robot"]]
    assert walked[0] == "acq_50hz.json" and "unknown_policy.json" in walked
    assert [x["policy"] for x in prom["exported_not_walked"]] == ["s1_50hz.json"]
    assert prom["by_track"]["walkcurr"]["walked_policies"] == ["acq_50hz.json"]

    s = rl_index.story("cw-root-acq", runs, state_dir.load_ledger(), pols, rows, [])
    assert s["real_walks"]["acq_50hz.json"]["legs"] == 4
    md = rl_index.story_md(s)
    assert "exported as acq_50hz.json" in md and "4 drive legs / 2 sessions" in md


def test_sweep_folders(tmp_path, monkeypatch):
    lab = tmp_path / "lab_runs"
    d = lab / "20260918_1804_gait_sweep3_hexapod2"
    d.mkdir(parents=True)
    (d / "gaits.json").write_text(json.dumps([
        {"gait": "walkteach", "file": "wt.json", "controller": "rl", "exposures": 3,
         "metrics": {"roll_rms_deg": 1.2, "pitch_rms_deg": 2.0, "chassis_speed_mm_s": 44.5},
         "verdict": "promising", "note": "n"},
        {"gait": "scripted", "file": "x.json", "controller": "scripted", "metrics": {}},
    ]))
    d2 = lab / "20260918_1844_walklong_hexapod2"
    d2.mkdir()
    (d2 / "results.json").write_text(json.dumps({"vx": 0.1, "trials": [
        {"arm": "wt_r1", "file": "wt.json", "samples": [
            {"t": 0.5, "engaged": False, "roll": 0.0},
            {"t": 1.0, "engaged": True, "roll": 3.0, "pitch": 4.0, "maxI": 0.2, "loop_hz": 90},
            {"t": 2.0, "engaged": True, "roll": -3.0, "pitch": -4.0, "maxI": 0.3, "loop_hz": 92}]},
        {"arm": "never", "file": "wt.json", "samples": [{"t": 0.1, "engaged": False}]}]}))
    (lab / "20260920-150649-aabb").mkdir()                 # a lab-service session: not a sweep
    monkeypatch.setattr(rl_index, "LAB_RUNS_DIRS", (lab,))
    sweeps = rl_index.load_sweeps()
    assert [s["session"] for s in sweeps] == ["20260918_1804_gait_sweep3_hexapod2",
                                              "20260918_1844_walklong_hexapod2"]
    assert sweeps[0]["robot"] == "hexapod2" and sweeps[0]["when"] == "2026-09-18T18:04"
    assert sweeps[1]["roll_rms_deg"] == 3.0 and sweeps[1]["max_current_a"] == 0.3
    agg = rl_index.summarise_real([], sweeps)["wt.json"]
    assert agg["sweep_exposures"] == 4 and agg["sweep_verdicts"] == {"promising": 1}
    assert agg["roll_rms_deg_med"] == 2.1 and agg["legs"] == 0


def _agg(**kw):
    base = {"legs": 0, "sessions": 0, "sweep_exposures": 0, "sweep_sessions": 0,
            "speed_ratio_med": None, "tilt_max_deg_med": None, "roll_rms_deg_med": None,
            "sweep_verdicts": {}}
    base.update(kw)
    return base


def test_walk_rank_prefers_smooth_walking_over_fast_rocking():
    smooth_walker = _agg(legs=29, speed_ratio_med=0.34, tilt_max_deg_med=7.9)
    fast_rocker = _agg(legs=23, speed_ratio_med=0.36, tilt_max_deg_med=16.0,
                       sweep_exposures=11, roll_rms_deg_med=3.8, sweep_verdicts={"poor": 1})
    smooth_but_stuck = _agg(legs=3, speed_ratio_med=0.06, tilt_max_deg_med=5.2)
    sweep_only = _agg(sweep_exposures=3, roll_rms_deg_med=3.3)
    sweep_only_poor = _agg(sweep_exposures=13, roll_rms_deg_med=5.2, sweep_verdicts={"poor": 1})
    order = sorted([sweep_only_poor, fast_rocker, sweep_only, smooth_but_stuck, smooth_walker],
                   key=rl_index.walk_rank)
    assert order == [smooth_walker, fast_rocker, smooth_but_stuck, sweep_only, sweep_only_poor]


# ------------------------------------------------------------ build
def test_build_writes_index_files(state_ledger, tmp_path, monkeypatch):
    root = state_ledger(LEDGER)
    (root / "OPERATOR_QUESTIONS.md").write_text(
        "# Operator questions\n\n## q_1 — OPEN\nfirst line\nsecond\n\n## q_2 — CLOSED (done)\nx\n")
    monkeypatch.setattr(rl_index, "LAB_RUNS_DIRS", (tmp_path / "none",))
    monkeypatch.setattr(rl_index, "ROBOTS_JSON", tmp_path / "no-robots.json")   # no LAN in tests
    out = tmp_path / "index"
    meta = rl_index.build(out, with_real=True, proto=tmp_path / "noproto")
    assert meta["runs"] == 4 and meta["ledger_fingerprint"] == state_dir.ledger_fingerprint()
    assert meta["open_questions"] == 1
    for name in ("INDEX.md", "runs.jsonl", "lineage.json", "policies.json", "real_walks.jsonl",
                 "real_sweeps.jsonl", "promising.json", "status_map.json", "open_questions.md",
                 "meta.json"):
        assert (out / name).exists(), name
    rows = [json.loads(l) for l in (out / "runs.jsonl").read_text().splitlines()]
    assert {r["run"] for r in rows} == {"cw-root", "cw-root-acq", "cw-root-acq-s1", "cw-other"}
    smap = json.loads((out / "status_map.json").read_text())
    assert smap["ACQ FAIL"] == {"outcome": "FAIL", "count": 1}
    idx = (out / "INDEX.md").read_text()
    assert "## 1. Policies that have walked" in idx and "cw-root-acq" in idx
    assert "q_1" in (out / "open_questions.md").read_text()
    assert "q_2" not in (out / "open_questions.md").read_text()
