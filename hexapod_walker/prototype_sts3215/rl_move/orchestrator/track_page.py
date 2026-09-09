"""Track drill-downs using the complete ledger and recorded cycle accounting."""
from __future__ import annotations

import collections
import json
import math
import pathlib
import re
import urllib.parse

_cost_cache = {}


def latest_runs(entries):
    """One experiment per run name; retry/status rows are not experiments."""
    latest = {}
    for entry in entries:
        if isinstance(entry, dict) and entry.get("run"):
            name = entry["run"]
            latest[name] = {**latest.get(name, {}), **entry}
    return sorted(latest.values(), key=lambda e: (e.get("created") or "", e["run"]),
                  reverse=True)


def recorded_cost(cycle, directory):
    """Read a terminal reported dollar amount, cached as logs grow."""
    raw = cycle.get("raw")
    if not raw:
        return None
    path = pathlib.Path(raw).resolve()
    if not path.is_relative_to(directory.resolve()):
        return None
    try:
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        cached = _cost_cache.get(str(path))
        if cached and cached[0] == key:
            return cached[1]
        with path.open("rb") as f:
            f.seek(max(0, stat.st_size - 262144))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
        value = None
        for line in reversed(lines):
            try:
                record = json.loads(line)
                cost = record.get("total_cost_usd")
                if record.get("type") == "result" and isinstance(cost, (float, int)):
                    if math.isfinite(cost) and cost >= 0:
                        value = float(cost)
                        break
            except (ValueError, AttributeError):
                continue
        _cost_cache[str(path)] = (key, value)
        return value
    except OSError:
        return None


def associated_cycles(tid, cycles, all_runs, track_of, directory):
    """Split shared cycle costs equally among declared tracks, not per run."""
    by_run = {e["run"]: track_of(e) for e in all_runs}
    result, seen = [], set()
    for cycle in cycles:
        identity = cycle.get("raw") or (cycle.get("stamp"), cycle.get("label"))
        if identity in seen:
            continue
        seen.add(identity)
        tracks = {by_run.get(name, "unassigned") for name in cycle.get("runs", [])}
        if tid not in tracks:
            continue
        cost = recorded_cost(cycle, directory)
        result.append({**cycle, "allocated_usd": cost / len(tracks) if cost is not None else None,
                       "shared": len(tracks) > 1})
    return sorted(result, key=lambda c: c.get("started", ""), reverse=True)


def model_label(identity):
    variant = identity.get("model_variant")
    if variant == "full_mesh" and identity.get("model_nmesh", 0) > 0:
        return f"Full CAD · {identity['model_nmesh']} meshes · {identity.get('model_mass_kg', '?')} kg"
    if variant in ("mesh_mjx_twin", "legacy_primitive"):
        return "Simplified simulation model"
    return "Model not recorded"


def cad_compositions(server, runs):
    """Find composed CAD demos whose folders are not named after runs."""
    known = {e["run"] for e in runs}
    found = {}
    root = server.EVAL_VIDEO_DIR
    for path in sorted(root.glob("hybrid*/**/summary.json"), reverse=True):
        try:
            data = json.loads(path.read_text())
            name = data.get("composition", {}).get("name", "")
            run = name.removesuffix(" hybrid")
            video = path.with_name("drive.mp4")
            if (run not in known or data.get("model_variant") != "full_mesh"
                    or data.get("model_nmesh", 0) <= 0 or not video.is_file()
                    or not video.resolve().is_relative_to(root.resolve())):
                continue
            if run not in found:
                found[run] = {"clips": [{"path": video.relative_to(root).as_posix(),
                                        "label": "Scripted stand/lower + learned walking",
                                        "model_label": model_label(data)}]}
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return found


def video_player(server, video, preload="none"):
    clips = video.get("clips") or ([video] if video.get("path") else [])
    if not clips:
        return "<span class='dim'>No video available yet</span>"
    clip = clips[0]
    url = "/media/" + urllib.parse.quote(str(clip["path"]), safe="/")
    label = server.esc(clip.get("label") or "MuJoCo evaluation")
    identity_label = clip.get("model_label")
    if not identity_label:
        root = server.EVAL_VIDEO_DIR.resolve()
        folder = (root / str(clip["path"])).resolve().parent
        identity = {}
        if folder.is_relative_to(root):
            while folder != root:
                for filename in ("summary.json", "report.json"):
                    try:
                        data = json.loads((folder / filename).read_text())
                        if "model_variant" in data:
                            identity = data
                            break
                    except (OSError, ValueError, TypeError):
                        pass
                if identity:
                    break
                folder = folder.parent
        identity_label = model_label(identity)
    return (f"<p class='dim'>{server.esc(identity_label)}</p>"
            f"<video controls muted playsinline preload='{preload}' "
            f"aria-label='{label}' src='{server.esc(url)}' "
            "style='width:100%;aspect-ratio:16/9;background:#000;border-radius:8px'></video>"
            f"<p class='dim'>{label} · <a href='{server.esc(url)}' target='_blank' rel='noopener'>Open video ↗</a></p>")


def render(server, tid, page=1):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", tid):
        return None
    registry = server._tracks.load()
    f = server.SNAP.get("fast", {})
    if tid not in registry and tid not in f.get("status_docs", {}):
        return None
    esc = server.esc
    meta = registry.get(tid, {})
    ledger_error = ""
    try:
        ledger_path = getattr(server, "LEDGER", server.HERE / "experiments.json")
        entries = json.loads(ledger_path.read_text())
        if not isinstance(entries, list):
            raise ValueError("ledger is not a list")
    except (OSError, ValueError):
        entries = []
        ledger_error = "Experiment ledger unavailable; totals are unavailable until it recovers."
    if hasattr(server, "current_entries"):
        all_runs = latest_runs(list(server.current_entries(entries).values()))
    else:
        all_runs = latest_runs(entries)
    runs = [e for e in all_runs if server.track_of_entry(e) == tid]
    per_page = 30
    pages = max(1, math.ceil(len(runs) / per_page))
    page = max(1, min(page, pages))
    page_runs = runs[(page - 1) * per_page:page * per_page]
    # Bound discovery work on large tracks; never attribute a parent's clip
    # to a similarly named child. The shared index owns artifact matching.
    targets = {e["run"] for e in runs[:60] + page_runs}
    videos = server.representative_videos(targets, [e["run"] for e in all_runs],
                                          {e["run"]: tid for e in runs})
    cad_videos = cad_compositions(server, runs)
    videos.update(cad_videos)
    rows = [e for e in entries if isinstance(e, dict) and server.track_of_entry(e) == tid]
    queued = [e for e in f.get("backlog", {}).get("queued", [])
              if server.track_of_entry(e) == tid]
    cycles = associated_cycles(tid, server._cycle_registry_entries(), all_runs,
                               server.track_of_entry, server.CYCLE_DIR)
    # Only live process observations establish activity; historical registry
    # entries sometimes retain 'running' after the process has exited.
    live_names = {name.strip() for c in f.get("cycles", [])
                  for name in (c.get("about") or "").split(",") if name.strip()}
    pending = {e["run"]: "analysis" for e in runs if e["run"] in live_names}
    doc = f.get("status_docs", {}).get(tid, {}).get("text", "")
    badge, _ = server._track_badge(tid, doc, runs, pending,
                                  meta.get("status", ""), meta.get("lifecycle", ""))
    if queued and badge not in ("ACTIVE NOW", "ANALYZING"):
        badge = "QUEUED"
    url = "/track/" + urllib.parse.quote(tid, safe="")
    name = meta.get("name", tid)
    body = ["<div class='brieflabel'>RESEARCH TRACK</div>",
            f"<h1>{esc(name)} <span class='badge'>{esc(badge)}</span></h1>",
            f"<p class='dim'>{esc(tid)} · Complete recorded experiment history</p>"]
    if ledger_error:
        body.append(f"<p class='warn'>{esc(ledger_error)}</p>")
    body.append("<section id='videos'><h2>Watch the robot in MuJoCo</h2>"
                "<p class='dim'>Full-CAD composed demos first, then available videos from the latest 60 experiments. "
                "Failures are shown too—check each verdict beside the footage.</p>")
    featured = ([e for e in runs if e["run"] in cad_videos]
                + [e for e in runs[:60] if videos.get(e["run"]) and e["run"] not in cad_videos])[:3]
    if featured:
        body.append("<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:16px'>")
        for e in featured:
            body.append("<article class='card' style='min-width:0;overflow-wrap:anywhere'>"
                        + video_player(server, videos[e["run"]], "metadata")
                        + f"<div>{server.run_link(e['run'])}</div>"
                        + f"<p class='dim'>{esc((e.get('created') or 'Unknown date')[:19])} · {esc(e.get('status', 'UNKNOWN'))}</p>"
                        + f"<p>{esc(str(e.get('verdict') or 'No verdict recorded yet.')[:240])}</p>"
                        + f"<a href='/run/{urllib.parse.quote(e['run'], safe='')}#behavior-preview'>All clips &amp; full result →</a></article>")
        body.append("</div>")
    else:
        body.append("<p>No evaluation video has been copied back for these experiments yet. "
                    "Older experiments below may have footage.</p>")
    body.append("</section>")
    counts = collections.Counter(e.get("status", "UNKNOWN") for e in runs)
    costs = [c["allocated_usd"] for c in cycles if c["allocated_usd"] is not None]
    body.append("<div class='grid'>")
    for value, label in [
        ("Unavailable" if ledger_error else len(runs), "unique experiments"),
        ("Unavailable" if ledger_error else sum(bool(e.get("verdict")) for e in runs), "with verdicts"),
        ("Unavailable" if ledger_error else counts.get("RUNNING", 0), "marked running"),
        (len(queued), "queued experiments"),
        (f"${sum(costs):,.2f}" if costs else "Unavailable", "attributed LLM spend"),
        ("Unavailable", "total spend including GPUs"),
    ]:
        body.append(f"<div class='card'><div class='n'>{esc(value)}</div><div class='l'>{label}</div></div>")
    body.append("</div>")
    body.append(f"<p class='dim'>LLM accounting: {len(costs)} of {len(cycles)} associated cycles have recorded costs. "
                "Shared cycles are split equally across their declared run tracks. "
                "This is an attribution estimate; cross-track work inside a cycle, unassigned cycles, "
                "missing logs, and GPU/idle-fleet charges are not included.</p>")
    body.append(f"<p>{len(rows)} ledger entries across {len(runs)} unique run names; "
                "retries and status updates are counted once per experiment. "
                "Refused launches are included in the history.</p>")
    if counts:
        body.append("<p class='dim'>" + " · ".join(f"{esc(k)}: {v}" for k, v in sorted(counts.items())) + "</p>")
    if meta.get("goal"):
        body.append(f"<h2>Goal</h2><p>{esc(meta['goal'])}</p>")
    result = server.latest_research_result(doc)
    body.append(f"<h2>Latest research result</h2><p class='dim'>{esc(result['date'])}</p>"
                f"<p>{esc(result['headline'])}</p>"
                f"<p><a href='/llm/doc/rl_docs/tracks/{esc(tid)}/STATUS.md'>Full research notes →</a></p>")
    if queued:
        body.append("<h2>Queued next</h2><ul>" + "".join(
            f"<li>{esc(e.get('run', '?'))}</li>" for e in queued) + "</ul>")
    body.append(f"<h2>Latest experiments</h2><p class='dim'>Newest launch first · page {page} of {pages}</p>")
    if not runs:
        body.append("<p>No experiments recorded for this track.</p>" if not ledger_error else "")
    else:
        body.append("<div style='overflow-x:auto'><table><tr><th>Experiment</th><th>Created (UTC)</th>"
                    "<th>Status</th><th>MuJoCo video</th><th>Verdict / hypothesis</th></tr>")
        for e in page_runs:
            detail = str(e.get("verdict") or e.get("hypothesis") or "Not recorded")
            player = (video_player(server, videos[e["run"]]) if videos.get(e["run"])
                      else "<span class='dim'>No video available yet</span>")
            body.append(f"<tr><td class='mono'>{server.run_link(e['run'])}</td>"
                        f"<td>{esc((e.get('created') or 'Unknown')[:19])}</td>"
                        f"<td>{esc(e.get('status', 'UNKNOWN'))}</td>"
                        f"<td><div style='width:260px'>{player}</div></td>"
                        f"<td><details><summary>{esc(detail[:180])}</summary><p>{esc(detail)}</p></details></td></tr>")
        body.append("</table></div>")
    nav = []
    if page > 1:
        nav.append(f"<a href='{url}?page={page-1}'>← Newer experiments</a>")
    if page < pages:
        nav.append(f"<a href='{url}?page={page+1}'>Older experiments →</a>")
    body.append("<p>" + " · ".join(nav) + "</p>")
    body.append("<h2>Recent associated analysis cycles</h2>")
    if not cycles:
        body.append("<p>No cycle-to-run associations recorded for this track.</p>")
    else:
        body.append("<table><tr><th>Started (UTC)</th><th>Cycle</th><th>Attributed LLM cost</th></tr>")
        for c in cycles[:20]:
            cost = c["allocated_usd"]
            amount = f"${cost:,.2f}" + (" (shared)" if c["shared"] else "") if cost is not None else "Unavailable"
            stamp = urllib.parse.quote(str(c.get("stamp", "")), safe="")
            body.append(f"<tr><td>{esc(c.get('started', ''))}</td>"
                        f"<td><a href='/cycle/{stamp}'>{esc(c.get('label', 'cycle'))}</a></td><td>{amount}</td></tr>")
        body.append("</table>")
    return server._page(name, body)
