"""rl_topics: skill/method tagging over RL runs and Robot Lab experiments, gait join."""
from __future__ import annotations

import json
import sqlite3

import rl_index
import rl_topics


def test_classify_by_name_tokens_cfg_and_track():
    assert "stand" in rl_topics.classify(["cw-stance50hz-rlonly-scratch-s0-canary2m"], "")
    tags = rl_topics.classify(["cw-stance50hz-rlonly-lowerrole-scratch-s1"], "")
    assert {"stand", "lower", "rl-only"} <= set(tags)
    assert "hold" in rl_topics.classify(["cw-stand50hz-holdbias5m"], "")
    assert "turn" in rl_topics.classify(["cw-walk50hz-x"], "", {"goal.walk_yaw_cmd": "1"})
    assert "turn" not in rl_topics.classify(["cw-walk50hz-x"], "", {"goal.walk_yaw_cmd": "0"})
    assert "rise" in rl_topics.classify(["cw-x"], "", {"goal.rise_height_mm": "40"})
    assert "amp" in rl_topics.classify(["cw-x"], "", track="amp")
    # sub-topics imply the parent, ordering follows TOPICS
    t = rl_topics.classify(["cw-x-lower-y"], "")
    assert t.index("stand") < t.index("lower")


def test_classify_prose_is_word_bounded_and_lab_only_topics_need_lab():
    assert "walk" in rl_topics.classify(["x"], "Can the robot walk faster?")
    assert "current" not in rl_topics.classify(["x"], "the current champion recipe")
    assert "current" in rl_topics.classify(["x"], "the over_current trip at 2.5 A")
    assert "sysid" not in rl_topics.classify(["sysid-hip-bode"], "sysid: hip Bode")            # RL run: lab-only
    assert "sysid" in rl_topics.classify(["sysid-hip-bode"], "sysid: hip Bode", lab=True)
    assert "instrumentation" not in rl_topics.classify(["cw-walk"], "video shows a clean gait")
    assert rl_topics.classify(["cw-zzz"], "") == []


def _runs(state_ledger):
    ledger = [
        {"run": "cw-stance-root", "status": "CANARY PASS", "phase": "canary", "track": "walkcurr",
         "created": "2026-09-01T00:00:00+00:00", "hypothesis": "Can rise/hold/lower be learned from scratch?",
         "extra_args": ["--cfg-set", "goal.rise_height_mm=40"]},
        {"run": "cw-stance-root-acq", "status": "PASS", "phase": "acquisition", "track": "walkcurr",
         "created": "2026-09-02T00:00:00+00:00", "parent": "cw-stance-root", "hypothesis": "Consolidate it.",
         "extra_args": ["--cfg-set", "goal.rise_height_mm=40"]},
        {"run": "cw-walk50hz-teach-s0", "status": "PASS", "phase": "acquisition", "track": "standwalk",
         "created": "2026-09-03T00:00:00+00:00", "hypothesis": "Scripted teacher all-heading walk.",
         "extra_args": ["--cfg-set", "goal.walk_pure=1"]},
    ]
    state_ledger(ledger)
    entries = rl_index.state_dir.load_ledger()
    return rl_index.load_runs(entries), entries


def _lab_db(path):
    con = sqlite3.connect(path)
    con.executescript("""
    create table plans(id text primary key, created_at text, title text, why text, protocol text, kind text,
                       build_spec text, force int, status text, status_note text, source text, updated_at text,
                       robot text, needs_robot int, intent text);
    create table runs(id text primary key, plan_id text, started_at text, finished_at text, status text,
                      exit_code int, run_dir text, summary_json text, log_tail text, robot text);
    create table learnings(id text primary key, created_at text, run_id text, text text);
    """)
    con.execute("insert into plans values('p1','2026-09-22T10:00:00+00:00','RL gait trial ws800: teach_50hz.json',"
                "'baseline vs newer gaits','', 'existing',null,0,'done','exit 0, 32 s','operator','','hexapod2',1,'test')")
    con.execute("insert into plans values('p2','2026-09-10T10:00:00+00:00','sysid: unloaded hip Bode, all 6 hips',"
                "'servo model','hip_bode_v1','existing',null,0,'done',null,'planner','','hexapod2',1,'test')")
    con.execute("insert into plans values('p3','2026-09-11T10:00:00+00:00','camera coverage check (apriltag-layout.snapshot.json)',"
                "'verify tags','', 'existing',null,0,'failed','freed by nothing','planner','','hexapod1',0,'test')")
    con.execute("insert into runs values('r1','p1','2026-09-22T10:01:00+00:00','2026-09-22T10:05:00+00:00','ok',0,'/x',"
                "'{\"gaits\": []}',null,'hexapod2')")
    con.execute("insert into learnings values('l1','2026-09-22T10:05:00+00:00','r1','[hexapod2] {\"policy\": \"teach_50hz.json\"}')")
    con.execute("insert into learnings values('l2','2026-09-22T10:06:00+00:00','r1','[hexapod2] speed_ratio 0.32, tilt fine')")
    con.commit()
    con.close()


def test_lab_experiments_and_gait_join(state_ledger, tmp_path):
    runs, entries = _runs(state_ledger)
    db = tmp_path / "lab2.sqlite3"
    _lab_db(db)
    lab = rl_topics.load_lab_experiments(db)
    assert [x["id"] for x in lab] == ["p2", "p3", "p1"]
    p1 = lab[-1]
    assert p1["policies"] == ["teach_50hz.json"] and p1["found"] == "speed_ratio 0.32, tilt fine"
    assert "walk" in p1["topics"] and "sysid" in lab[0]["topics"] and "instrumentation" in lab[1]["topics"]

    pols = {"teach_50hz.json": {**rl_index._blank_policy("teach_50hz.json"), "run": "cw-walk50hz-teach-s0",
                                "track": "standwalk", "on_robots": ["hexapod2"]}}
    d = rl_topics.compute(runs, entries, pols, {}, lab)
    assert d["run_topics"]["cw-stance-root-acq"][:2] == ["stand", "rise"]
    assert d["lineage"]["cw-stance-root"] == ["cw-stance-root", "cw-stance-root-acq"]
    gaits = {g["policy"]: g for g in d["gaits"]}
    assert set(gaits) == {"teach_50hz.json"}          # apriltag-layout.snapshot.json is not a policy
    g = gaits["teach_50hz.json"]
    assert g["run"] == "cw-walk50hz-teach-s0" and g["lab_trials"] == 1 and g["lineage_runs"] == 1

    page = rl_topics.topic_page("stand", runs, d["run_topics"], lab, d["lineage"])
    assert "`cw-stance-root`" in page and "2 |" in page and "cw-walk50hz-teach-s0" not in page
    assert "## Robot Lab experiments (0" in page
    walk = rl_topics.topic_page("walk", runs, d["run_topics"], lab, d["lineage"])
    assert "RL gait trial ws800" in walk and "speed_ratio 0.32" in walk
    assert "teach_50hz.json" in rl_topics.gait_page("cw-walk50hz-teach-s0", d["gaits"], runs, lab, d["lineage"])
    idx = rl_topics.index_page(d["run_topics"], lab, runs, d["gaits"])
    assert "| Stand: rise, hold, lower, stance | 2 |" in idx


def test_build_writes_topic_pages(state_ledger, tmp_path, monkeypatch):
    runs, entries = _runs(state_ledger)
    monkeypatch.setattr(rl_topics, "LAB2_DB", tmp_path / "missing.sqlite3")
    meta = rl_topics.build(tmp_path, runs, entries, {}, {})
    assert meta["lab_experiments"] == 0 and meta["untagged_runs"] == 0
    assert (tmp_path / "topics" / "INDEX.md").exists() and (tmp_path / "topics" / "lower.md").exists()
    t = json.loads((tmp_path / "topics.json").read_text())
    assert set(t["run_topics"]) == set(runs)
