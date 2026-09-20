"""doc_compact.py -- move stale journal entries out of the files cycles read.

The journals under the state dir are prepend/append-only prose that the
decision cycles `cat` for facts; by 2026-09-20 CURRENT_TRUTHS.md was 465 KB,
OPERATOR_QUESTIONS.md 506 KB, RL_LOG.md 256 KB and walkcurr's STATUS.md
259 KB. Run-level facts now live in the ledger + rl_index (`ops.sh index`),
so the journals only need to carry recent findings and standing rulings.

Nothing is deleted. Every compaction writes
`<state>/archive/doc_compaction_<UTC date>/`:

    pre/<file>                       byte-for-byte copy of each file before the edit
    <file>__archived_entries.md      the entries moved out, in their original order

Rules (each one explicit, each one a pure function of the text):

  CURRENT_TRUTHS.md   keep the durable sections (from the `# CURRENT TRUTHS` title
                      on), dated findings from the last KEEP_DAYS, and any dated
                      entry whose headline names the operator / a RULING / an ORDER;
                      archive older dated findings. The title moves to the top.
  OPERATOR_QUESTIONS  keep the doctrine header, every entry marked OPEN, and
                      every entry dated within KEEP_DAYS; archive CLOSED / ANSWERED /
                      unmarked assume-and-go entries older than that.
  RL_LOG.md           keep the header and the last KEEP_DAYS of `- MM-DD ...` lines.
  tracks/*/STATUS.md  for journals made of `## YYYY-MM-DD ...` entries (newest
                      first): keep the head and the newest KEEP_ENTRIES entries.

Usage:  python3 doc_compact.py [--state DIR] [--today YYYY-MM-DD] [--execute]
Dry-run by default: prints what would move and the before/after sizes.
Stdlib only (runs on the controller's system python3).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KEEP_DAYS = 7
KEEP_ENTRIES = 8
RULING_WORDS = re.compile(r"\b(operator|RULING|ORDER|Lukas)\b")
DATE_RE = re.compile(r"(2026-\d\d-\d\d)")
QSTAMP_RE = re.compile(r"q_(\d{4})(\d\d)(\d\d)T")
LOGLINE_RE = re.compile(r"^- (\d\d)-(\d\d) ")


def _split_sections(text: str, header_re: str) -> tuple[str, list[str]]:
    """(head, [section, ...]) where each section starts with a matching header line."""
    parts = re.split(rf"(?m)^(?={header_re})", text)
    return parts[0], parts[1:]


def _headline_date(headline: str, year_hint: int = 2026) -> date | None:
    m = QSTAMP_RE.search(headline)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = DATE_RE.search(headline)
    if m:
        return date.fromisoformat(m.group(1))
    m = re.search(r"\b(\d\d)-(\d\d)\b", headline)
    if m:
        return date(year_hint, int(m.group(1)), int(m.group(2)))
    return None


def _note(kind: str, today: date, archive_rel: str, what: str) -> str:
    return (f"<!-- compacted {today.isoformat()} by orchestrator/doc_compact.py: {what} "
            f"moved to {archive_rel}; nothing deleted. Run-level facts: `ops.sh index story <run>`. -->\n")


# ------------------------------------------------------------ CURRENT_TRUTHS
def compact_truths(text: str, today: date, archive_rel: str) -> tuple[str, list[str]]:
    """Cycles PREPEND findings, so the `# CURRENT TRUTHS` title sits mid-file
    with dated findings above and below it and the durable sections
    (Mission, contracts, gotchas, ...) at the end. Classify every section by
    its headline: dated -> finding (kept if recent or a ruling), undated ->
    durable (kept, in order). Output: title, recent findings, durable."""
    cutoff = today - timedelta(days=KEEP_DAYS)
    head, sections = _split_sections(text, r"#{1,2} ")
    title, findings, moved, durable = "", [], [], []
    for s in sections:
        h = s.splitlines()[0]
        if h.startswith("# "):
            title = title or s
            continue
        d = _headline_date(h)
        if d is None and not h.startswith("## CORRECTION"):
            durable.append(s)
        elif d is None or d >= cutoff or RULING_WORDS.search(h):
            findings.append(s)
        else:
            moved.append(s)
    if not moved:
        return text, []
    title_line, _, title_rest = (title or "# CURRENT TRUTHS - accepted facts and rulings\n").partition("\n")
    out = (title_line + "\n" + _note("truths", today, archive_rel,
                                     f"{len(moved)} dated findings older than {cutoff.isoformat()}")
           + title_rest.strip("\n") + ("\n\n" if title_rest.strip() else "\n")
           + "## Recent findings (newest first; older ones are in archive/)\n\n"
           + head.lstrip("\n") + "".join(findings).rstrip("\n") + "\n\n"
           + "".join(durable))
    return out, moved


# ------------------------------------------------------------ OPERATOR_QUESTIONS
def compact_questions(text: str, today: date, archive_rel: str) -> tuple[str, list[str]]:
    cutoff = today - timedelta(days=KEEP_DAYS)
    head, sections = _split_sections(text, r"## ")
    keep, moved = [], []
    for s in sections:
        h = s.splitlines()[0]
        d = _headline_date(h)
        is_open = bool(re.search(r"\bOPEN\b", h))
        if is_open or d is None or d >= cutoff:
            keep.append(s)
        else:
            moved.append(s)
    if not moved:
        return text, []
    out = head.rstrip("\n") + "\n\n" + _note(
        "questions", today, archive_rel,
        f"{len(moved)} CLOSED/ANSWERED/assume-and-go entries older than {cutoff.isoformat()}"
        " (every entry still marked OPEN is kept here)") + "\n" + "".join(keep)
    return out, moved


# ------------------------------------------------------------ RL_LOG
def compact_rl_log(text: str, today: date, archive_rel: str) -> tuple[str, list[str]]:
    cutoff = today - timedelta(days=KEEP_DAYS)
    keep, moved = [], []
    for line in text.splitlines(keepends=True):
        m = LOGLINE_RE.match(line)
        if m and date(today.year, int(m.group(1)), int(m.group(2))) < cutoff:
            moved.append(line)
        else:
            keep.append(line)
    if not moved:
        return text, []
    out = "".join(keep)
    out = re.sub(r"(?m)^Last compacted: .*$", f"Last compacted: {today.isoformat()} UTC. This active "
                 f"file keeps only recent cycle", out, count=1)
    out = out.replace("## Recent Lines\n", "## Recent Lines\n" + _note(
        "rl_log", today, archive_rel, f"{len(moved)} cycle lines older than {cutoff.isoformat()}"), 1)
    return out, moved


# ------------------------------------------------------------ track STATUS
def compact_track(text: str, today: date, archive_rel: str, track: str) -> tuple[str, list[str]]:
    head, sections = _split_sections(text, r"(?:## \d{4}-\d\d-\d\d|# \(compacted)")
    entries = [s for s in sections if s.startswith("## ")]
    if len(entries) <= KEEP_ENTRIES:
        return text, []
    keep, moved = entries[:KEEP_ENTRIES], entries[KEEP_ENTRIES:]
    # older compaction markers (`# (compacted ...)`) travel with the archive
    moved_text = [s for s in sections if s not in keep]
    if not head.strip():
        head = f"# {track} — track journal (newest first)\n\n"
    out = (head.rstrip("\n") + "\n" + _note("track", today, archive_rel,
                                            f"{len(moved)} entries older than the newest {KEEP_ENTRIES}")
           + "\n" + "".join(keep))
    return out, moved_text


# ------------------------------------------------------------ driver
def run(state: Path, today: date, execute: bool, out=None) -> dict:
    out = out or sys.stdout
    stamp = today.isoformat()
    archive = state / "archive" / f"doc_compaction_{stamp}"
    archive_rel = f"archive/doc_compaction_{stamp}/"
    jobs = [
        ("CURRENT_TRUTHS.md", lambda t: compact_truths(t, today, archive_rel)),
        ("OPERATOR_QUESTIONS.md", lambda t: compact_questions(t, today, archive_rel)),
        ("RL_LOG.md", lambda t: compact_rl_log(t, today, archive_rel)),
    ]
    for p in sorted((state / "rl_docs" / "tracks").glob("*/STATUS.md")):
        tr = p.parent.name
        jobs.append((str(p.relative_to(state)), lambda t, tr=tr: compact_track(t, today, archive_rel, tr)))
    report = {}
    for rel, fn in jobs:
        p = state / rel
        if not p.is_file():
            continue
        text = p.read_text(errors="replace")
        new, moved = fn(text)
        report[rel] = {"before": len(text), "after": len(new), "moved": len(moved)}
        print(f"{rel:42} {len(text):>8} -> {len(new):>8} bytes, {len(moved):3} entries moved", file=out)
        if not moved or not execute:
            continue
        (archive / "pre").mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, archive / "pre" / p.name.replace("STATUS.md", f"{p.parent.name}_STATUS.md"))
        arch_name = rel.replace("/", "__").replace(".md", "") + "__archived_entries.md"
        (archive / arch_name).write_text(
            f"# Archived {stamp} from {rel} by orchestrator/doc_compact.py "
            f"(original order; nothing edited)\n\n" + "".join(moved))
        tmp = p.with_suffix(p.suffix + ".tmp-compact")
        tmp.write_text(new)
        os.replace(tmp, p)
    if execute:
        (archive / "README.md").write_text(
            f"# doc_compaction_{stamp}\n\nWritten by orchestrator/doc_compact.py on {stamp}.\n"
            f"`pre/` holds byte-for-byte copies of every file before the edit; the\n"
            f"`*__archived_entries.md` files hold the entries that were moved out, in\n"
            f"their original order. Rules: {__doc__.split('Rules')[1].split('Usage:')[0].strip()}\n")
        print(f"archive: {archive}", file=out)
    else:
        print("(dry run; add --execute to write)", file=out)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", type=Path, default=Path(os.environ.get("HEXAPOD_STATE_DIR") or
                                                        Path(__file__).resolve().parents[1] / ".state"))
    ap.add_argument("--today", type=date.fromisoformat,
                    default=datetime.now(timezone.utc).date())
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args(argv)
    if not (a.state / "ledger").is_dir():
        print(f"{a.state} does not look like a state dir (no ledger/)", file=sys.stderr)
        return 2
    run(a.state, a.today, a.execute)
    return 0


if __name__ == "__main__":
    sys.exit(main())
