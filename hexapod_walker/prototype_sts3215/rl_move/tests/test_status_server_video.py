from __future__ import annotations

import json
import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCH))

import status_server  # noqa: E402


def _reset_video_cache() -> None:
    status_server._video_index_cache.update(
        {"at": 0.0, "targets": (), "videos": {}}
    )


def test_representative_video_prefers_gate_walk_and_longest_run(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(status_server, "EVAL_VIDEO_DIR", tmp_path)
    _reset_video_cache()
    base = "cw-demo"
    seed = "cw-demo-s1"

    base_dir = tmp_path / "cw_demo_donegate"
    seed_dir = tmp_path / "cw_demo_s1_donegate"
    base_dir.mkdir()
    seed_dir.mkdir()
    (base_dir / "rise_sto_0.mp4").write_bytes(b"rise")
    (base_dir / "walk_det_0.mp4").write_bytes(b"walk")
    (seed_dir / "walk_det_0.mp4").write_bytes(b"seed")

    videos = status_server.representative_videos(
        [base, seed], [base, seed])

    assert videos[base]["path"] == "cw_demo_donegate/walk_det_0.mp4"
    assert videos[seed]["path"] == "cw_demo_s1_donegate/walk_det_0.mp4"


def test_media_path_stays_inside_eval_video_dir(
        monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "evals"
    root.mkdir()
    video = root / "run" / "walk_det_0.mp4"
    video.parent.mkdir()
    video.write_bytes(b"video")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"private")
    (root / "escape.mp4").symlink_to(outside)
    monkeypatch.setattr(status_server, "EVAL_VIDEO_DIR", root)

    assert status_server._resolve_media_path("run/walk_det_0.mp4") == video
    assert status_server._resolve_media_path("../outside.mp4") is None
    assert status_server._resolve_media_path("escape.mp4") is None
    assert status_server._resolve_media_path("run/report.json") is None


def test_media_byte_ranges_support_video_seeking() -> None:
    assert status_server._media_byte_range("", 100) is None
    assert status_server._media_byte_range("bytes=10-19", 100) == (10, 19)
    assert status_server._media_byte_range("bytes=90-", 100) == (90, 99)
    assert status_server._media_byte_range("bytes=-12", 100) == (88, 99)


def test_video_preview_is_clickable_and_url_encoded() -> None:
    markup = status_server.video_preview(
        {"path": "a run/walk_det_0.mp4", "label": "walk <det>"})
    assert "&#9654; preview" in markup
    assert "a%20run/walk_det_0.mp4" in markup
    assert "walk &lt;det&gt;" in markup
    assert "preload='none'" in markup

    assert "not available" in status_server.video_preview(None)


def test_run_page_puts_behavior_preview_before_ledger(
        monkeypatch, tmp_path: Path) -> None:
    run = "cw-video-demo"
    orch = tmp_path / "rl_move" / "orchestrator"
    orch.mkdir(parents=True)
    (orch / "experiments.json").write_text(json.dumps([
        {"run": run, "status": "PASS", "track": "demo",
         "created": "2026-09-03T12:00:00+00:00"},
    ]))
    monkeypatch.setattr(status_server, "HERE", orch)
    monkeypatch.setattr(status_server, "PROTO", tmp_path)
    monkeypatch.setitem(status_server.SNAP, "fast", {
        "run_videos": {run: {
            "path": "cw_video_demo_gate/walk_det_0.mp4",
            "label": "gate/walk_det_0.mp4",
        }},
    })

    page = status_server.render_run_page(run)

    assert page is not None
    assert "Behavior preview" in page
    assert "/media/cw_video_demo_gate/walk_det_0.mp4" in page
    assert page.index("Behavior preview") < page.index("Ledger history")
