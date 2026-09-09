import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
import status_server as server
import track_page


@pytest.fixture
def track_data(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HERE", tmp_path)
    monkeypatch.setattr(server, "LEDGER", tmp_path / "experiments.json", raising=False)
    monkeypatch.setattr(server, "CYCLE_DIR", tmp_path)
    monkeypatch.setattr(server, "EVAL_VIDEO_DIR", tmp_path)
    monkeypatch.setattr(server._tracks, "load", lambda: {
        "joystick": {"name": "Joystick walking", "goal": "Follow commands", "lifecycle": "open"},
        "empty": {"name": "Empty"}})
    entries = [{"run": f"run-{i:02}", "track": "joystick", "status": "FINISHED",
                "created": f"2026-09-{i%28+1:02}T12:00:00", "verdict": "<script>bad()</script>"}
               for i in range(35)]
    entries += [{"run": "run-00", "status": "FAILED", "track": "joystick"},
                {"run": "other", "track": "amp", "status": "FINISHED"}]
    (tmp_path / "experiments.json").write_text(json.dumps(entries))
    monkeypatch.setattr(server, "SNAP", {"fast": {"ledger": entries[-1:], "status_docs": {},
                                                 "backlog": {"queued": []}}})
    monkeypatch.setattr(server, "_cycle_registry_entries", lambda: [])
    monkeypatch.setattr(server, "representative_videos", lambda *args: {})
    return tmp_path


def test_full_history_deduplicated_paginated_and_escaped(track_data):
    page = server.render_track_page("joystick")
    assert "35</div>" in page and "37</div>" not in page
    assert "36 ledger entries across 35 unique run names" in page
    assert "FAILED: 1" in page
    assert "page 1 of 2" in page
    assert "<script>bad()" not in page
    assert "&lt;script&gt;" in page
    assert "Older experiments" in page
    second = server.render_track_page("joystick", 2)
    assert "page 2 of 2" in second
    assert "Newer experiments" in second
    assert "total spend including GPUs" in page and "Unavailable" in page


def test_unknown_empty_and_missing_ledger(track_data):
    assert server.render_track_page("../joystick") is None
    assert server.render_track_page("notreal") is None
    assert "No experiments recorded" in server.render_track_page("empty")
    (track_data / "experiments.json").write_text("broken")
    assert "Experiment ledger unavailable" in server.render_track_page("joystick")


def test_runtime_ledger_and_canonical_entries_take_precedence(track_data, monkeypatch):
    runtime = track_data / "runtime.json"
    runtime.write_text('[{"run":"runtime-only","track":"joystick","status":"FINISHED"}]')
    monkeypatch.setattr(server, "LEDGER", runtime)
    monkeypatch.setattr(server, "current_entries", lambda rows: {e["run"]: e for e in rows}, raising=False)
    page = server.render_track_page("joystick")
    assert "runtime-only" in page
    assert "1 ledger entries across 1 unique run names" in page


def test_videos_are_visible_before_stats_and_include_failed_results(track_data, monkeypatch):
    monkeypatch.setattr(server, "representative_videos", lambda *args: {
        "run-00": {"clips": [{"path": "run_00_gate/walk_det_0.mp4", "label": "walking"}]}})
    page = server.render_track_page("joystick", 2)
    assert page.index("Watch the robot in MuJoCo") < page.index("unique experiments")
    assert "<video controls" in page
    assert "/media/run_00_gate/walk_det_0.mp4" in page
    assert "preload='metadata'" in page and "preload='none'" in page
    assert "FAILED" in page and "All clips &amp; full result" in page
    assert "No video available yet" in page


def test_cad_comparison_is_attributed_by_manifest_and_featured(track_data):
    folder = track_data / "hybrid_comparison" / "candidate"
    folder.mkdir(parents=True)
    (folder / "drive.mp4").write_bytes(b"test")
    (folder / "summary.json").write_text(json.dumps({
        "composition": {"name": "run-00 hybrid"}, "model_variant": "full_mesh",
        "model_nmesh": 34, "model_mass_kg": 4.80573}))
    page = server.render_track_page("joystick")
    assert "Full CAD · 34 meshes · 4.80573 kg" in page
    assert "/media/hybrid_comparison/candidate/drive.mp4" in page
    assert "Scripted stand/lower + learned walking" in page
    assert track_page.cad_compositions(server, [{"run": "unrelated"}]) == {}
    assert track_page.model_label({"model_variant": "mesh_mjx_twin"}) == "Simplified simulation model"
    assert track_page.model_label({"model_source": "mesh"}) == "Model not recorded"


def test_cost_allocation_coverage_cache_and_shared_cycles(tmp_path):
    raw = tmp_path / "cycle.jsonl"
    raw.write_text(json.dumps({"type": "result", "total_cost_usd": 12}) + "\n")
    cycle = {"raw": str(raw), "runs": ["a", "b", "c"], "started": "2026-09-09"}
    runs = [{"run": "a", "track": "joystick"}, {"run": "b", "track": "joystick"},
            {"run": "c", "track": "amp"}]
    rows = track_page.associated_cycles("joystick", [cycle, cycle], runs,
                                        lambda e: e["track"], tmp_path)
    assert len(rows) == 1 and rows[0]["allocated_usd"] == 6
    raw.write_text('{"type":"result","total_cost_usd":0}\n')
    assert track_page.recorded_cost(cycle, tmp_path) == 0
    raw.write_text('{"type":"result","total_cost_usd":NaN}\n')
    assert track_page.recorded_cost(cycle, tmp_path) is None
    assert track_page.recorded_cost({"raw": str(tmp_path.parent / "outside")}, tmp_path) is None


def test_authenticated_route_and_bad_pagination(track_data, monkeypatch):
    monkeypatch.setattr(server, "TOKEN", "test-only")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(base + "/track/joystick")
        assert err.value.code == 403
        req = urllib.request.Request(base + "/track/joystick?page=oops",
                                     headers={"Cookie": "status_token=test-only"})
        with urllib.request.urlopen(req) as response:
            assert "Joystick walking" in response.read().decode()
        req = urllib.request.Request(base + "/track/missing",
                                     headers={"Cookie": "status_token=test-only"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req)
        assert err.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
