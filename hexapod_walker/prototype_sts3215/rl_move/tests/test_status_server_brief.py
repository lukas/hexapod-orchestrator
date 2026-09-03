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


def test_latest_research_result_uses_dated_done_section() -> None:
    text = """# todaypolicy status

Last updated: 2026-08-30. This is the delivery track.

## DONE (2026-08-30): bundle-v1 PACKAGED, ALL BARS PASS

The full-mesh demo had zero falls and all six legs cycling.
"""
    result = status_server.latest_research_result(text)
    assert result["date"] == "2026-08-30"
    assert result["headline"].startswith("DONE (2026-08-30)")
    assert "zero falls" in result["headline"]


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
    assert "Research tracks" in html
    assert "Latest result" in html
    assert "cw-walkcurr-overnight1" in html
    assert "/run/cw-walkcurr-overnight1" in html
    assert "/llm/doc/rl_docs/tracks/walkcurr/STATUS.md" in html


def test_research_brief_marks_retired_track_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        status_server._tracks,
        "load",
        lambda: {
            "walkcurr": {
                "name": "Prior-free walking curriculum",
                "status": "RETIRED: negative scope finding",
            },
        },
    )
    f = {
        "status_docs": {
            "walkcurr": {
                "name": "walkcurr",
                "text": ("# walkcurr\n\n## RETIRED (2026-08-31)\n\n"
                         "The final seeds did not walk."),
            },
        },
        "ledger": [],
    }

    brief = status_server.research_brief(f, {})
    track = brief["topics"][0]
    assert track["badge"] == "RETIRED"
    assert track["cls"] == "retired"
    assert "no further agent-initiated launches" in track["where"]
    assert "Retired: walkcurr" in brief["summary"]


def test_done_gate_heading_is_not_mistaken_for_done_track() -> None:
    text = """# active track

Last updated: 2026-09-03. A new experiment is running.

## Next

Read the experiment.

## DONE gate

This describes the future completion criteria.
"""
    badge, cls = status_server._track_badge("newtrack", text, [], {})
    assert badge == "ACTIVE"
    assert cls == "active"


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
    assert "Research tracks" in body
    assert "Snapshot still collecting" in body
    assert "href='/now'" in body
