"""Research-track registry (operator restructure, 2026-08-11).

The campaign runs as parallel research tracks, each with its own goal
and status doc (rl_docs/tracks/). All runs live in ONE W&B project
(operator: tags, not separate projects — nothing moves); each run is
tagged `track:<id>` so the W&B UI filters per track. tracks.json is
the single source of truth; this module is the one shared accessor.

Containment rule (operator): analysis of a run in one track fires
follow-up jobs ONLY in that track, unless a big insight is explicitly
escalated (see ORCHESTRATOR_PROMPT.md "Research tracks").
"""
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ENTITY = "l2k2"
PROJECT = "hexapod-balance"       # one project for every track
DEFAULT_TRACK = "hw"
TAG_PREFIX = "track:"

# Run-name prefix -> track, for entries/launches that don't say. Order
# matters: first match wins. Everything unmatched is the hw mainline.
PREFIX_MAP = (
    ("cw-arch-", "arch"),
    ("cw-gru-", "arch"),
    ("cw-quad-", "quad"),
    ("cw-nobc-", "nobc"),
    ("cw-gait-", "nobc"),
    ("cw-turn-", "turn"),
    ("cw-mt-", "multitask"),
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
