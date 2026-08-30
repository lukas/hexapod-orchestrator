"""Research-track registry.

The campaign's active tracks live in tracks.json. All W&B-backed runs
share ONE project (tags, not separate projects); each run is tagged
`track:<id>`. tracks.json is the single source of truth; this module
is the one shared accessor.

Containment rule: agent-initiated follow-ups go only to registered
tracks. Operator-launched out-of-scope runs are triaged honestly but
never spawn agent follow-ups.
"""
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ENTITY = "l2k2"
PROJECT = "hexapod-balance"       # one project for every track
DEFAULT_TRACK = "joystick"
TAG_PREFIX = "track:"

# Run-name prefix -> track, for entries/launches that don't say. Order
# matters: first match wins. Everything unmatched is the joystick
# mainline. (Pre-08-21 runs already carry a "track" field in the
# ledger; this map only serves new/untagged names.)
PREFIX_MAP = (
    ("cw-amp-", "amp"),
    ("mjx-amp-", "amp"),
    ("paper-cpg-", "cpg"),
    ("cw-cpg-", "cpg"),
    ("cpg-", "cpg"),
    ("cw-walkcurr-", "walkcurr"),
    ("walkcurr-", "walkcurr"),
    ("cw-standwalk-", "standwalk"),
    ("standwalk-", "standwalk"),
    ("cw-todaypolicy-", "todaypolicy"),
    ("cw-workingpolicy-", "todaypolicy"),
    ("todaypolicy-", "todaypolicy"),
)


def load() -> dict:
    return json.loads((HERE / "tracks.json").read_text())


def ids() -> list[str]:
    return list(load().keys())


def tag(track: str | None) -> str:
    t = track if track in load() else DEFAULT_TRACK
    return TAG_PREFIX + t


def project_path() -> str:
    return f"{ENTITY}/{PROJECT}"


def all_project_paths() -> list[str]:
    """Kept for call-site compatibility; tags-not-projects means there
    is exactly one project."""
    return [project_path()]


def infer(run_name: str) -> str:
    for pref, tr in PREFIX_MAP:
        if run_name.startswith(pref):
            return tr
    return DEFAULT_TRACK


def find_wandb_run(api, name: str):
    """Latest W&B run with this display name."""
    runs = list(api.runs(project_path(), filters={"display_name": name}))
    if runs:
        return sorted(runs, key=lambda x: x.created_at)[-1]
    return None
