from __future__ import annotations

import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[1] / "orchestrator"
sys.path.insert(0, str(ORCH))

import status_server  # noqa: E402


def test_latest_research_summary_prefers_top_dated_update() -> None:
    text = """# AMP status

Last updated: 2026-08-30 - M5 GATE GREEN. **Evidence** is in [the run](x).

## Older notes

This should not be used.
"""
    summary = status_server.latest_research_summary(text)
    assert "M5 GATE GREEN" in summary
    assert "**" not in summary
    assert "[the run]" not in summary


def test_latest_research_summary_uses_now_block_after_preface() -> None:
    text = """# walkcurr status

**Phase-sv rule preface:** old structural guidance.

## Now (2026-08-30 - overnight fanout)

The bigger search is the current open experiment. It should be visible first.

## Older notes

Do not summarize this first.
"""
    summary = status_server.latest_research_summary(text)
    assert summary.startswith("Now (2026-08-30 - overnight fanout):")
    assert "bigger search" in summary
    assert "Phase-sv" not in summary


def test_research_brief_renders_running_track_first(monkeypatch) -> None:
    monkeypatch.setattr(
        status_server._tracks,
        "load",
        lambda: {
            "walkcurr": {"name": "Prior-free walking curriculum"},
            "amp": {"name": "AMP locomotion"},
        },
    )
    f = {
        "status_docs": {
            "walkcurr": {
                "name": "walkcurr",
                "text": "# walkcurr\n\n## Now\n\nSearching without priors.",
            },
            "amp": {
                "name": "amp",
                "text": "# amp\n\nLast updated: 2026-08-30 - gate green.",
            },
        },
        "ledger": [
            {
                "run": "cw-walkcurr-overnight1",
                "track": "walkcurr",
                "status": "RUNNING",
            },
            {"run": "cw-amp-m5-pass", "track": "amp", "status": "FINISHED"},
        ],
    }

    brief = status_server.research_brief(f, {})
    assert brief["topics"][0]["id"] == "walkcurr"
    assert brief["topics"][0]["badge"] == "ACTIVE NOW"
    assert "Active now: walkcurr" in brief["summary"]

    html = "".join(status_server.render_research_brief(brief))
    assert "Research Brief" in html
    assert "cw-walkcurr-overnight1" in html
    assert "/run/cw-walkcurr-overnight1" in html


def test_llm_research_brief_links_to_track_status(monkeypatch) -> None:
    monkeypatch.setattr(
        status_server._tracks,
        "load",
        lambda: {"walkcurr": {"name": "Prior-free walking curriculum"}},
    )
    monkeypatch.setitem(
        status_server.SNAP,
        "fast",
        {
            "status_docs": {
                "walkcurr": {
                    "name": "walkcurr",
                    "text": "# walkcurr\n\n## Now\n\nSearching without priors.",
                },
            },
            "ledger": [],
        },
    )

    md = status_server.research_brief_md("https://hexapod.example", "")
    assert "# Research brief" in md
    assert "## walkcurr -" in md
    assert ("https://hexapod.example/llm/doc/rl_docs/tracks/walkcurr/"
            "STATUS.md") in md


def test_memorable_dashboard_paths_are_official() -> None:
    assert {"/now", "/research", "/dashboard", "/status"} <= (
        status_server.DASHBOARD_PATHS
    )


def test_render_first_snapshot_still_has_research_brief(monkeypatch) -> None:
    monkeypatch.setitem(status_server.SNAP, "fast", {})
    monkeypatch.setitem(status_server.SNAP, "slow", {})

    body = status_server.render("https://hexapod.example")
    assert "Research Brief" in body
    assert "Snapshot still collecting" in body
    assert "href='/now'" in body
