"""Bounded eval-video paths and short-lived, file-specific access signatures."""
from __future__ import annotations

import hashlib
import hmac
import pathlib
import re
import time
import urllib.parse

VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mov"})
VIDEO_MAX_BYTES = 32 * 1024 * 1024
VIDEO_LINK_TTL = 3600
VIDEO_LINK_MAX_TTL = 24 * 3600


def _canonical_video_path(rel: str) -> str | None:
    """Require one unambiguous relative path before signing or resolving it."""
    if not isinstance(rel, str) or not rel or "\\" in rel or "\x00" in rel:
        return None
    path = pathlib.PurePosixPath(rel)
    if (path.is_absolute() or ".." in path.parts or path.as_posix() != rel
            or path.suffix.lower() not in VIDEO_EXTENSIONS):
        return None
    return rel


def resolve_video(root: pathlib.Path, rel: str) -> pathlib.Path | None:
    """Resolve a nonempty, bounded video beneath root, including symlink checks."""
    if _canonical_video_path(rel) is None:
        return None
    try:
        root = pathlib.Path(root).resolve()
        path = (root / rel).resolve()
        if (not path.is_relative_to(root)
                or path.suffix.lower() not in VIDEO_EXTENSIONS
                or not path.is_file()
                or not 0 < path.stat().st_size <= VIDEO_MAX_BYTES):
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return path


def sign_video_path(rel: str, key: str, expires: int) -> str:
    """Sign one canonical path and expiration without exposing the shared key."""
    if (_canonical_video_path(rel) is None or not key
            or type(expires) is not int or expires <= 0):
        raise ValueError("a canonical video path, key and expiration are required")
    payload = f"hexapod-eval-video-v1\x00{rel}\x00{expires}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_video_signature(rel: str, key: str, query: str,
                           now: float | None = None) -> bool:
    """Accept an unexpired signature for only this file, at most 24 hours ahead."""
    if _canonical_video_path(rel) is None or not key:
        return False
    try:
        params = urllib.parse.parse_qs(query, keep_blank_values=True,
                                      max_num_fields=20)
        expirations = params.get("expires", [])
        signatures = params.get("sig", [])
        if len(expirations) != 1 or len(signatures) != 1:
            return False
        expires_text, signature = expirations[0], signatures[0]
        if (not re.fullmatch(r"[1-9][0-9]{0,11}", expires_text)
                or not re.fullmatch(r"[0-9a-f]{64}", signature)):
            return False
        expires = int(expires_text)
        current = time.time() if now is None else now
        if not current < expires <= current + VIDEO_LINK_MAX_TTL:
            return False
        expected = sign_video_path(rel, key, expires)
    except (TypeError, ValueError, UnicodeError):
        return False
    return hmac.compare_digest(signature, expected)
