from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

import pytest

ORCH = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCH))

import media_access  # noqa: E402

KEY = "test-only-media-signing-key"
REL = "a run/walk_det_0.mp4"
NOW = 2_000_000_000


def _query(rel: str = REL, key: str = KEY,
           expires: int = NOW + media_access.VIDEO_LINK_TTL) -> str:
    return urllib.parse.urlencode({
        "expires": expires,
        "sig": media_access.sign_video_path(rel, key, expires),
    })


def test_video_signature_is_scoped_to_path_key_and_expiration() -> None:
    query = _query()
    assert media_access.verify_video_signature(REL, KEY, query, now=NOW)
    assert KEY not in query
    assert not media_access.verify_video_signature(
        "a run/walk_det_1.mp4", KEY, query, now=NOW)
    assert not media_access.verify_video_signature(REL, "other", query, now=NOW)
    assert not media_access.verify_video_signature(REL, "", query, now=NOW)
    assert not media_access.verify_video_signature(
        REL, KEY, query, now=NOW + media_access.VIDEO_LINK_TTL)
    assert not media_access.verify_video_signature(
        REL, KEY, query.replace(str(NOW + 3600), str(NOW + 7200)), now=NOW)
    assert not media_access.verify_video_signature(
        REL, KEY, _query(expires=NOW + 86401), now=NOW)
    assert media_access.verify_video_signature(
        REL, KEY, _query(expires=NOW + 86400), now=NOW)


@pytest.mark.parametrize("query", [
    "", "expires=", "sig=", "expires=tomorrow&sig=123", "expires=-1&sig=123",
    "expires=2000003600&sig=", "expires=2000003600&sig=%ZZ",
    "expires=02000003600&sig=" + "a" * 64,
    _query() + "&expires=2000003600", _query() + "&sig=",
    _query() + "&" + "&".join(f"extra{i}=x" for i in range(21)),
])
def test_video_signature_rejects_malformed_and_duplicate_fields(query: str) -> None:
    assert not media_access.verify_video_signature(REL, KEY, query, now=NOW)


@pytest.mark.parametrize("rel", [
    "", "/walk.mp4", "../walk.mp4", "run/../walk.mp4", "run\\walk.mp4",
    "./walk.mp4", "run//walk.mp4", "run/./walk.mp4", "run/report.json",
    "run/walk.mp4\x00",
])
def test_video_path_rejects_noncanonical_paths(tmp_path: Path, rel: str) -> None:
    assert media_access.resolve_video(tmp_path, rel) is None
    assert not media_access.verify_video_signature(rel, KEY, _query(), now=NOW)
    with pytest.raises(ValueError):
        media_access.sign_video_path(rel, KEY, NOW + 3600)


def test_resolver_rejects_symlink_escape_and_invalid_files(
        monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "videos"
    root.mkdir()
    video = root / "walk.mp4"
    video.write_bytes(b"video")
    assert media_access.resolve_video(root, "walk.mp4") == video
    assert media_access.resolve_video(root, "missing.mp4") is None
    (root / "empty.mp4").touch()
    assert media_access.resolve_video(root, "empty.mp4") is None
    (root / "directory.mp4").mkdir()
    assert media_access.resolve_video(root, "directory.mp4") is None

    outside = tmp_path / "private.mp4"
    outside.write_bytes(b"private")
    (root / "escape.mp4").symlink_to(outside)
    assert media_access.resolve_video(root, "escape.mp4") is None
    (root / "subdir").symlink_to(tmp_path, target_is_directory=True)
    assert media_access.resolve_video(root, "subdir/private.mp4") is None
    (root / "report.json").write_bytes(b"private")
    (root / "hidden.mp4").symlink_to(root / "report.json")
    assert media_access.resolve_video(root, "hidden.mp4") is None

    monkeypatch.setattr(media_access, "VIDEO_MAX_BYTES", 4)
    assert media_access.resolve_video(root, "walk.mp4") is None
