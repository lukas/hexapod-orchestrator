"""Select a run's own eval reports before similarly named experiments."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


# Standard output directories produced by pod_eval.py. A suffix after a tag
# is a historical/recheck variant, available by querying its full directory.
REPORT_TAGS = ("gate", "owncfg", "session", "mixedsession", "joygate")


@dataclass(frozen=True)
class ReportSelection:
    paths: list[Path]
    exact: bool
    other_matches: int = 0

    def notice(self, query: str) -> str:
        if not self.exact:
            return (f"[FALLBACK: no exact report directory for {query!r}. "
                    "These name matches may be variants or different runs; "
                    "check each path before attributing its results to this run.]")
        if self.other_matches:
            return (f"[Exact report directories for {query!r}; "
                    f"{self.other_matches} other name matches excluded. "
                    "Query a full directory name to read a historical variant.]")
        return ""


def select_reports(root: Path, query: str) -> ReportSelection:
    """Prefer literal directories and bare run_{gate,owncfg,session,...}.

    Preserve old cw_walk_ omissions and explicit suffix queries. Broad name
    matches are a labelled fallback, never a reason to drop an older exact
    gate. In particular, run_s0_nostdanneal_gate is not run_s0's gate.
    """
    snake = query.replace("-", "_")
    stems = [snake]
    if snake.startswith("cw_walk_"):
        stems.append(snake.removeprefix("cw_walk_"))
    exact_names = {}
    for stem in stems:
        exact_names.setdefault(stem, -1)  # explicit report-directory query
        for rank, tag in enumerate(REPORT_TAGS):
            exact_names.setdefault(f"{stem}_{tag}", rank)
    # The trailing boundary also prevents acq1 from selecting acq1b.
    patterns = [re.compile(re.escape(stem) + r"(?:_|$)") for stem in stems]
    matches = [path for path in root.glob("*/report.json")
               if path.is_file()
               and any(p.search(path.parent.name) for p in patterns)]
    exact = [path for path in matches if path.parent.name in exact_names]
    if exact:
        exact.sort(key=lambda p: (exact_names[p.parent.name],
                                  -p.stat().st_mtime, p.parent.name))
        return ReportSelection(exact, True, len(matches) - len(exact))
    matches.sort(key=lambda p: (-p.stat().st_mtime, p.parent.name))
    return ReportSelection(matches, False)
