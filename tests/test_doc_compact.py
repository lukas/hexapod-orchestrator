"""doc_compact: journal compaction moves stale entries to archive/, loses nothing."""
from __future__ import annotations

import re
from datetime import date

import doc_compact as dc

TODAY = date(2026, 9, 20)          # KEEP_DAYS=3 -> cutoff = 2026-09-17
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
    # KEEP_DAYS=3, TODAY=2026-09-20 -> cutoff=2026-09-17 (`< cutoff` moves).
    text = ("# RL_LOG - recent cycle log\n\nLast compacted: 2026-09-14 UTC. This active file keeps only recent cycle\n"
            "lines.\n\n## Recent Lines\n- 09-14 12:00 old line\n- 09-16 23:59 old line 2\n"
            "- 09-17 00:00 boundary kept\n- 09-20 16:09 IDLE: nothing runnable\n")
    out, moved = dc.compact_rl_log(text, TODAY, ARCH)
    assert moved == ["- 09-14 12:00 old line\n", "- 09-16 23:59 old line 2\n"]
    assert "- 09-17 00:00 boundary kept" in out and "- 09-20 16:09" in out
    assert "Last compacted: 2026-09-20 UTC" in out and "## Recent Lines\n<!-- compacted" in out


def test_track_keeps_newest_entries_by_date_when_prepended():
    entries = [_sec(f"## 2026-09-{d:02d} ~10:0x (refill cycle) -- entry {d}", f"e{d}\n") for d in range(20, 8, -1)]
    text = "".join(entries[:5]) + "# (compacted 2026-09-14)\n\n" + "".join(entries[5:])
    out, moved = dc.compact_track(text, TODAY, ARCH, "walkcurr")
    assert out.startswith("# walkcurr — track journal\n")
    assert out.count("\n## 2026-09-") == dc.KEEP_ENTRIES
    # KEEP_ENTRIES=4: the newest 4 by date are 20,19,18,17 regardless of KEEP_ENTRIES's
    # historical value -- pin to the constant, not a hardcoded day, so a future
    # KEEP_ENTRIES tweak doesn't silently desync this assertion again.
    kept_days = {20 - k for k in range(dc.KEEP_ENTRIES)}
    for d in range(20, 8, -1):
        assert (f"e{d}\n" in out) == (d in kept_days)
    assert any(m.startswith("# (compacted 2026-09-14)") for m in moved)   # old marker travels along
    assert sum(1 for m in moved if m.startswith("## ")) == len(entries) - dc.KEEP_ENTRIES
    short = "# amp\n\nprose only, no dated entries\n"
    assert dc.compact_track(short, TODAY, ARCH, "amp") == (short, [])


def test_track_keeps_newest_entries_by_date_when_appended():
    """Regression for the 2026-09-28 standwalk bug: that track's cycles
    APPEND new entries (oldest right after the head, newest at the
    bottom) rather than prepending, so a position-based `entries[:N]`
    kept four stale entries and archived ~18 genuinely-newer ones
    (09-27/09-28 gait-timing work) out from under every later cycle.
    Compaction must key on the parsed headline date, not file position,
    so it behaves correctly under this convention too."""
    entries = [_sec(f"## 2026-09-{d:02d} ~10:0x (refill cycle) -- entry {d}", f"e{d}\n")
               for d in range(9, 21)]   # ascending: oldest (9) first, newest (20) last
    text = "".join(entries)
    out, moved = dc.compact_track(text, TODAY, ARCH, "standwalk")
    assert out.count("\n## 2026-09-") == dc.KEEP_ENTRIES
    kept_days = {20 - k for k in range(dc.KEEP_ENTRIES)}
    for d in range(9, 21):
        assert (f"e{d}\n" in out) == (d in kept_days)
    # original within-file order is preserved among the kept entries
    kept_order = [int(m.group(1)) for m in re.finditer(r"entry (\d+)", out)]
    assert kept_order == sorted(kept_order)


def test_newest_track_entry_picks_by_date_not_position():
    """Regression for the 2026-09-28 ops.sh `board` bug: `board` used a
    bare first-`re.search` match to summarize a track's latest state,
    which is only correct for prepending (newest-first) tracks. An
    appending track (standwalk) showed a stale ~04:1x entry all day
    while ~11:5x closures landed underneath it. `newest_track_entry`
    must find the true newest by parsed date under either convention."""
    prepended = ("".join(_sec(f"## 2026-09-{d:02d} ~10:0x -- entry {d}", f"e{d}\n")
                          for d in range(20, 17, -1)))
    assert dc.newest_track_entry(prepended).startswith("## 2026-09-20 ~10:0x -- entry 20")

    appended = ("".join(_sec(f"## 2026-09-{d:02d} ~10:0x -- entry {d}", f"e{d}\n")
                         for d in range(18, 21)))
    assert dc.newest_track_entry(appended).startswith("## 2026-09-20 ~10:0x -- entry 20")

    # same-day tie broken by the intraday '~HH:Dx' tag, not file position --
    # the later tag wins whichever order the two entries appear in the file
    later_first = (_sec("## 2026-09-28 ~11:5x -- later same day", "later\n")
                   + _sec("## 2026-09-28 ~04:1x -- earlier same day", "earlier\n"))
    assert "later same day" in dc.newest_track_entry(later_first)
    earlier_first = (_sec("## 2026-09-28 ~04:1x -- earlier same day", "earlier\n")
                      + _sec("## 2026-09-28 ~11:5x -- later same day", "later\n"))
    assert "later same day" in dc.newest_track_entry(earlier_first)

    assert dc.newest_track_entry("no dated entries here\n") == ""

    multi = dc.newest_track_entry(appended, n=2)
    assert multi.splitlines()[0].startswith("## 2026-09-20")
    assert multi.splitlines()[1] == "e20"


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
