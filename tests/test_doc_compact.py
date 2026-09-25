"""doc_compact: journal compaction moves stale entries to archive/, loses nothing."""
from __future__ import annotations

from datetime import date

import doc_compact as dc

TODAY = date(2026, 9, 20)          # cutoff = 2026-09-13
ARCH = "archive/doc_compaction_2026-09-20/"


def _sec(head, body="body\n"):
    return f"{head}\n\n{body}\n"


def test_truths_keeps_recent_rulings_and_durable_sections_title_first():
    text = (_sec("## new finding (2026-09-18 ~03:1x, walkcurr track, refill cycle)", "n\n")
            + _sec("## old finding (2026-09-10 ~08:0x, standwalk track, triage cycle)", "o\n")
            + _sec("## CORRECTION (same cycle, ~30min later): the entry below is wrong", "c\n")
            + _sec("## OPERATOR ORDER + RULING (2026-09-10, Lukas via Claude): control.hz=50", "r\n")
            + "# CURRENT TRUTHS - accepted facts and rulings\n\n"
            + _sec("## older finding below the title (2026-09-09 ~10:0x, amp track, refill cycle)", "ob\n")
            + _sec("## Mission", "m\n") + _sec("## Known Tooling Gotchas", "g\n"))
    out, moved = dc.compact_truths(text, TODAY, ARCH)
    assert [m.splitlines()[0][:12] for m in moved] == ["## old findi", "## older fin"]
    assert out.startswith("# CURRENT TRUTHS")
    heads = [l for l in out.splitlines() if l.startswith("#")]
    assert heads == ["# CURRENT TRUTHS - accepted facts and rulings",
                     "## Recent findings (newest first; older ones are in archive/)",
                     "## new finding (2026-09-18 ~03:1x, walkcurr track, refill cycle)",
                     "## CORRECTION (same cycle, ~30min later): the entry below is wrong",
                     "## OPERATOR ORDER + RULING (2026-09-10, Lukas via Claude): control.hz=50",
                     "## Mission", "## Known Tooling Gotchas"]
    # every byte of body text is either kept or archived
    for body in ("n\n", "o\n", "c\n", "r\n", "ob\n", "m\n", "g\n"):
        assert body in out or any(body in m for m in moved)
    assert "doc_compact.py" in out and ARCH in out


def test_truths_untouched_when_nothing_is_old():
    text = _sec("## fresh (2026-09-19, speed track, refill cycle)") + "# CURRENT TRUTHS\n\n" + _sec("## Mission")
    assert dc.compact_truths(text, TODAY, ARCH) == (text, [])


def test_questions_keep_open_and_recent_archive_the_rest():
    head = "# Operator questions\n\ndoctrine...\n\n---\n\n"
    text = (head
            + _sec("## q_20260815T1920Z — OPEN", "old but open\n")
            + _sec("## q_20260815T2050Z — CLOSED (08-15 ~22:0x UTC, by fb_x)", "closed\n")
            + _sec("## q_20260822T2140Z — ANSWERED: paper-CPG contextual winner", "answered\n")
            + _sec("## 2026-08-22 — phasedir rung A stopped: approve repricing?", "unmarked old\n")
            + _sec("## q_20260918T0311Z — walkyaw (d) scope ruling (assume-and-go)", "recent unmarked\n")
            + _sec("## no date at all", "undated\n"))
    out, moved = dc.compact_questions(text, TODAY, ARCH)
    assert [m.splitlines()[0] for m in moved] == [
        "## q_20260815T2050Z — CLOSED (08-15 ~22:0x UTC, by fb_x)",
        "## q_20260822T2140Z — ANSWERED: paper-CPG contextual winner",
        "## 2026-08-22 — phasedir rung A stopped: approve repricing?"]
    assert out.startswith(head.rstrip("\n"))
    for kept in ("old but open", "recent unmarked", "undated"):
        assert kept in out
    assert "closed\n" not in out


def test_rl_log_keeps_header_and_recent_lines():
    text = ("# RL_LOG - recent cycle log\n\nLast compacted: 2026-09-14 UTC. This active file keeps only recent cycle\n"
            "lines.\n\n## Recent Lines\n- 09-10 12:00 old line\n- 09-12 23:59 old line 2\n"
            "- 09-13 00:00 boundary kept\n- 09-20 16:09 IDLE: nothing runnable\n")
    out, moved = dc.compact_rl_log(text, TODAY, ARCH)
    assert moved == ["- 09-10 12:00 old line\n", "- 09-12 23:59 old line 2\n"]
    assert "- 09-13 00:00 boundary kept" in out and "- 09-20 16:09" in out
    assert "Last compacted: 2026-09-20 UTC" in out and "## Recent Lines\n<!-- compacted" in out


def test_track_keeps_newest_entries_and_adds_a_title_when_missing():
    entries = [_sec(f"## 2026-09-{d:02d} ~10:0x (refill cycle) -- entry {d}", f"e{d}\n") for d in range(20, 8, -1)]
    text = "".join(entries[:5]) + "# (compacted 2026-09-14)\n\n" + "".join(entries[5:])
    out, moved = dc.compact_track(text, TODAY, ARCH, "walkcurr")
    assert out.startswith("# walkcurr — track journal (newest first)\n")
    assert out.count("\n## 2026-09-") == dc.KEEP_ENTRIES
    assert "e20\n" in out and "e13\n" in out and "e12\n" not in out
    assert any(m.startswith("# (compacted 2026-09-14)") for m in moved)   # old marker travels along
    assert sum(1 for m in moved if m.startswith("## ")) == len(entries) - dc.KEEP_ENTRIES
    short = "# amp\n\nprose only, no dated entries\n"
    assert dc.compact_track(short, TODAY, ARCH, "amp") == (short, [])


def test_run_dry_then_execute_archives_everything(tmp_path, capsys):
    state = tmp_path / "state"
    (state / "ledger").mkdir(parents=True)
    (state / "rl_docs" / "tracks" / "walkcurr").mkdir(parents=True)
    (state / "CURRENT_TRUTHS.md").write_text(
        _sec("## old (2026-09-01 ~01:0x, walkcurr track, triage cycle)", "OLDBODY\n")
        + "# CURRENT TRUTHS - accepted facts and rulings\n\n" + _sec("## Mission", "m\n"))
    (state / "OPERATOR_QUESTIONS.md").write_text("# Operator questions\n\n---\n\n"
                                                 + _sec("## q_20260815T2050Z — CLOSED", "QBODY\n"))
    (state / "RL_LOG.md").write_text("# RL_LOG\n\nLast compacted: never\n\n## Recent Lines\n- 09-01 old\n- 09-20 new\n")
    track = "".join(_sec(f"## 2026-09-{d:02d} entry", f"T{d}\n") for d in range(19, 9, -1))
    (state / "rl_docs" / "tracks" / "walkcurr" / "STATUS.md").write_text(track)
    (state / "rl_docs" / "runs").mkdir()
    (state / "rl_docs" / "runs" / "cw-x.md").write_text("# cw-x\ngenerated\n")
    before = {p: p.read_text() for p in state.rglob("*.md")}

    dc.run(state, TODAY, execute=False)
    assert {p: p.read_text() for p in state.rglob("*.md")} == before      # dry run writes nothing
    assert "(dry run" in capsys.readouterr().out

    report = dc.run(state, TODAY, execute=True)
    arch = state / "archive" / "doc_compaction_2026-09-20"
    assert report["CURRENT_TRUTHS.md"]["moved"] == 1 and report["RL_LOG.md"]["moved"] == 1
    assert report["rl_docs/tracks/walkcurr/STATUS.md"]["moved"] == 10 - dc.KEEP_ENTRIES
    for name in ("CURRENT_TRUTHS.md", "OPERATOR_QUESTIONS.md", "RL_LOG.md", "walkcurr_STATUS.md"):
        assert (arch / "pre" / name).exists(), name
    assert (arch / "pre" / "CURRENT_TRUTHS.md").read_text() == before[state / "CURRENT_TRUTHS.md"]
    assert "OLDBODY" in (arch / "CURRENT_TRUTHS__archived_entries.md").read_text()
    assert "OLDBODY" not in (state / "CURRENT_TRUTHS.md").read_text()
    assert "QBODY" in (arch / "OPERATOR_QUESTIONS__archived_entries.md").read_text()
    assert "- 09-01 old" in (arch / "RL_LOG__archived_entries.md").read_text()
    assert "T10\n" in (arch / "rl_docs__tracks__walkcurr__STATUS__archived_entries.md").read_text()
    assert (arch / "README.md").exists()
    assert report["rl_docs/runs/"]["moved"] == 1
    assert not (state / "rl_docs" / "runs").exists()
    assert (arch / "rl_docs_runs" / "cw-x.md").exists()
    # second run is a no-op
    assert all(v["moved"] == 0 for v in dc.run(state, TODAY, execute=True).values())
