"""rl_index.py -- derived indexes over the RL campaign's records.

The ledger (3400+ per-run JSON files), the journals (CURRENT_TRUTHS.md,
track STATUS.md, OPERATOR_QUESTIONS.md) and the Robot Lab's real-world run
folders each answer part of "what happened", but none of them is joined to
the others and the ledger's `status` field has grown ~200 spellings. This
module derives, never edits, and answers three questions directly:

  1. What are the most promising experiments?      -> `promising`
  2. How was a particular policy trained?           -> `story <run>` / `lineage <run>`
  3. Did it walk on the real robot, and how well?   -> `real [<policy|run>]`

`build` writes the same answers as small files for web/MCP/agent readers
(INDEX.md, runs.jsonl, lineage.json, policies.json, real_walks.jsonl,
promising.json, status_map.json, open_questions.md, meta.json).

Joins used (all by name, verified 2026-09-20 on every exported RL policy):

  ledger run  `cw-foo-bar`
    -> checkpoint  rl_move/sim/policies/ppo_goal_cw_foo_bar.zip
    -> exported    linux_control/policies/<name>.json   (meta.source = that zip)
    -> robot       ~/.hexapod_policies/<name>.json       (same file)
    -> real walk   <lab run>/walk_summary.json legs[].policy == <name>.json

Nothing here writes to the ledger; `launch_run.py update` uses `outcome()`
and `coerce_hardware_ready()` so new verdicts carry the canonical fields.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import statistics
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import state_dir
from ledger_view import current_entries
from roots import PROTO

WANDB_RUN_URL = "https://wandb.ai/l2k2/hexapod-balance/runs/{id}"
POLICIES_DIR = "linux_control/policies"            # under PROTO
TRACK_DOCS_DIR = "rl_docs/tracks"                  # under PROTO (manifests)
LAB_RUNS_DIRS = (
    Path.home() / ".hexapod" / "lab_runs",         # every lab-service session
    Path(os.environ.get("HEXAPOD_LAB2_DATA_DIR",
                        Path.home() / "Library" / "Application Support"
                        / "Hexapod Lab" / "v2")) / "runs",   # Lab v2 registry
)
LAB2_DB = Path(os.environ.get("HEXAPOD_LAB2_DATA_DIR",
                              Path.home() / "Library" / "Application Support"
                              / "Hexapod Lab" / "v2")) / "lab2.sqlite3"
ROBOTS_JSON = Path.home() / ".hexapod" / "robots.json"     # robot -> base url
EXTRA_POLICY_DIRS = [Path(p).expanduser() for p in
                     os.environ.get("HEXAPOD_POLICY_DIRS", "").split(":") if p]

# ------------------------------------------------------------ outcomes
# One closed vocabulary over the ledger's free-text `status`. The raw value
# is kept; `outcome` is derived (and stored alongside by launch_run update).
OUTCOMES: dict[str, str] = {
    "PASS": "gate met at the run's own phase/scope",
    "PARTIAL": "gate partly met, or a pass with a named residual",
    "CONTINUE": "mechanism healthy, gate not yet met; budget continues",
    "FAIL": "behavioural gate failed",
    "CANARY_PASS": "mechanism-health canary: mechanism engaged (no skill judgement)",
    "CANARY_FAIL": "mechanism-health canary: mechanism frozen / did not engage",
    "CANARY_FAIL_INFRA": "canary died of infrastructure; no read on the mechanism",
    "INFORMATIVE": "no gate decision; recorded as evidence (null, flat, note)",
    "INVALID": "execution invalid or inconclusive; no read on the hypothesis",
    "VERDICTED": "finished with a verdict whose head names no category; read it",
    "UNVERDICTED": "training finished, no verdict yet",
    "RUNNING": "training now",
    "INTENT": "recorded intent, never launched",
    "CRASHED": "launch or trainer failure before any result",
    "KILLED": "stopped by a cycle or the operator before completion",
    "SUPERSEDED": "duplicate / superseded / reconstructed bookkeeping row",
    "REFUSED": "launcher guardrail blocked it; no GPU time spent",
    "OTHER": "status not recognised -- extend outcome() and status_map.json",
}
# A real drive leg that covers less than this fraction of the commanded speed
# is "barely moving": smooth or not, it is not a walking result yet.
MIN_WALKING_RATIO = 0.15

# Outcomes that mean "the hypothesis got a real read".
DECIDED = ("PASS", "PARTIAL", "CONTINUE", "FAIL", "CANARY_PASS", "CANARY_FAIL",
           "INFORMATIVE", "VERDICTED")
POSITIVE = ("PASS", "PARTIAL")


def _norm(s) -> str:
    return re.sub(r"[\s_:/–—-]+", " ", str(s or "").strip().upper()).strip()


def _word(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}\b", text) for w in words)


def _categorise(text: str, phase: str) -> str | None:
    """Map one normalised status/verdict head to an outcome, or None."""
    t = text
    if not t:
        return None
    if t.startswith("REFUSED"):
        return "REFUSED"
    if t == "RUNNING":
        return "RUNNING"
    if t in ("INTENT", "STALE INTENT"):
        return "INTENT"
    if (t.startswith("KILLED") or t.startswith("STOP") or t.startswith("SELF KILLED")
            or t in ("ABORTED", "DEAD")):
        return "KILLED"
    if _word(t, "SUPERSEDED", "DUPLICATE", "RECONSTRUCTED", "IMPORT ERA STUB",
             "LEDGER HYGIENE") or t == "NOOP":
        return "SUPERSEDED"
    if t.startswith("FAILED") or _word(t, "CRASH", "CRASHED", "DEFECTIVE", "BUGGED",
                                        "LAUNCH FAILURE"):
        return "CRASHED"
    if "CANARY" in t or (phase == "canary" and _word(t, "MECHANISM")):
        if _word(t, "INFRASTRUCTURE", "INFRA"):
            return "CANARY_FAIL_INFRA"
        if _word(t, "FAIL"):
            return "CANARY_FAIL"
        if _word(t, "PASS", "CONTINUE"):
            return "CANARY_PASS"
        return None
    if _word(t, "INVALID", "INCONCLUSIVE", "UNDERTRAINED", "MISALIGNED"):
        return "INVALID"
    if t.startswith("INFORMATIVE") or t.startswith("NO EFFECT") or t in (
            "FLAT", "FLAT REGRESSED", "INFRA NOTE"):
        return "INFORMATIVE"
    if _word(t, "PARTIAL"):
        return "PARTIAL"
    if _word(t, "CONTINUE", "CONTINUED"):
        return "CONTINUE"
    if _word(t, "PASS", "PASSED"):
        return "PASS"
    if _word(t, "FAIL", "MISS"):
        return "FAIL"
    return None


def outcome(entry: dict) -> str:
    """Canonical outcome for a ledger entry (see OUTCOMES)."""
    phase = str(entry.get("phase") or "").lower()
    st = _norm(entry.get("status"))
    cat = _categorise(st, phase)
    if cat and st not in ("FINISHED", "DONE", "EVALUATED", "VERDICTED"):
        return cat
    verdict = str(entry.get("verdict") or "").strip()
    if not verdict:
        if st in ("FINISHED", "DONE", "EVALUATED", "VERDICTED"):
            return "UNVERDICTED"
        return "OTHER"
    head = _norm(verdict)[:160]
    cat = _categorise(head, phase)
    if cat in ("REFUSED", "RUNNING", "INTENT"):
        cat = None   # a verdict that merely mentions these is not one
    return cat or "VERDICTED"


def coerce_hardware_ready(value) -> bool | None:
    """True / False / None from the ledger's bool-or-string history."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("true", "yes", "y", "1", "ready"):
        return True
    if s in ("false", "no", "n", "0", "not ready"):
        return False
    return None


# ------------------------------------------------------------ ledger rows
def _track_of(e: dict) -> str:
    if e.get("track"):
        return str(e["track"])
    try:
        import tracks as _tracks
        return _tracks.infer(str(e.get("run", "")))
    except Exception:
        return "?"


def _stem(name: str) -> str:
    """Checkpoint stem of a run name or checkpoint path: `ppo_goal_cw_x.zip`
    and `cw-x` both become `cw_x`."""
    s = str(name or "").strip()
    s = s.rsplit("/", 1)[-1]
    if s.endswith(".zip"):
        s = s[:-4]
    if s.startswith("ppo_goal_"):
        s = s[len("ppo_goal_"):]
    return s.replace("-", "_")


def parse_args_list(extra_args) -> tuple[dict, dict]:
    """`extra_args` -> ({cfg key: value}, {flag: value|True})."""
    cfg, flags = {}, {}
    args = list(extra_args or [])
    i = 0
    while i < len(args):
        a = str(args[i])
        if a == "--cfg-set" and i + 1 < len(args):
            k, _, v = str(args[i + 1]).partition("=")
            cfg[k] = v
            i += 2
        elif a.startswith("--"):
            if i + 1 < len(args) and not str(args[i + 1]).startswith("--"):
                flags[a] = str(args[i + 1])
                i += 2
            else:
                flags[a] = True
                i += 1
        else:
            i += 1
    return cfg, flags


def first_sentence(text, limit: int = 220) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t:
        return ""
    m = re.search(r"(.+?[.!?])(\s|$)", t)
    s = m.group(1) if m and len(m.group(1)) <= limit else t[:limit]
    return s if len(s) <= limit else s[:limit - 1] + "…"


def load_runs(entries=None) -> dict[str, dict]:
    """Current attempt per run, as compact index rows keyed by run name."""
    if entries is None:
        entries = state_dir.load_ledger()
    current = current_entries(entries)
    by_stem = {_stem(r): r for r in current}
    rows: dict[str, dict] = {}
    for run, e in current.items():
        parent_raw = e.get("parent")
        parent = None
        if parent_raw:
            parent = current.get(str(parent_raw)) and str(parent_raw) \
                or by_stem.get(_stem(parent_raw))
        _, flags = parse_args_list(e.get("extra_args"))
        rows[run] = {
            "run": run,
            "track": _track_of(e),
            "phase": e.get("phase"),
            "scope": e.get("assessment_scope"),
            "created": e.get("created"),
            "steps": e.get("steps"),
            "seed": e.get("seed", flags.get("--seed")),
            "parent": parent,
            "parent_raw": parent_raw if parent_raw and parent != parent_raw else None,
            "status": e.get("status"),
            "outcome": outcome(e),
            "hardware_ready": coerce_hardware_ready(e.get("hardware_ready")),
            "wandb_id": e.get("wandb_id"),
            "pod": e.get("pod"),
            "checkpoint": e.get("final_checkpoint") or e.get("checkpoint"),
            "hypothesis": first_sentence(e.get("hypothesis"), 300),
            "verdict": first_sentence(e.get("verdict"), 300),
            "ledger_seq": e.get(state_dir.SEQ_KEY),
        }
    # lineage
    children = defaultdict(list)
    for r in rows.values():
        if r["parent"]:
            children[r["parent"]].append(r["run"])
    for r in rows.values():
        r["children"] = sorted(children.get(r["run"], []))
        chain, seen, cur = [], set(), r["parent"]
        while cur and cur in rows and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            cur = rows[cur]["parent"]
        r["ancestors"] = chain
        r["root"] = chain[-1] if chain else r["run"]
    return rows


# ------------------------------------------------------------ policies
def _blank_policy(name: str) -> dict:
    return {"policy": name, "kind": "?", "source_checkpoint": None, "run": None,
            "track": None, "training_hz": None, "obs_dim": None, "notes": None,
            "on_robots": [], "manifests": [], "real": None}


ROBOT_CACHE_TTL_S = 3600.0   # reuse the cached robot policy lists this long before re-fetching


def robot_policy_lists(robots_json: Path | None = None, cache: Path | None = None,
                       timeout: float = 2.0, ttl_s: float = ROBOT_CACHE_TTL_S) -> dict[str, list[dict]]:
    """robot -> its `/api/rl/policies` rows (file, source, notes, obs_dim, ...).

    The robots are the authority on what has actually been deployed: files
    uploaded to ~/.hexapod_policies never pass through the code tree.
    Cache-first: the copy from the last build (<index dir>/robot_policies.json)
    is reused while younger than `ttl_s`; otherwise each robot in
    ~/.hexapod/robots.json is fetched live (short timeout, an unreachable
    robot falls back to its cached rows)."""
    robots_json = ROBOTS_JSON if robots_json is None else robots_json
    cached: dict = {}
    if cache and cache.is_file():
        try:
            cached = json.loads(cache.read_text())
            if cached and (datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime) < ttl_s:
                return cached
        except (OSError, ValueError):
            cached = {}
    out: dict[str, list[dict]] = {}
    try:
        robots = json.loads(robots_json.read_text()) if robots_json.is_file() else {}
    except (OSError, ValueError):
        robots = {}
    for name, r in robots.items():
        url = (r or {}).get("url")
        rows = None
        if url:
            try:
                with urllib.request.urlopen(f"{url.rstrip('/')}/api/rl/policies", timeout=timeout) as fh:
                    rows = json.loads(fh.read()).get("policies") or []
            except Exception:
                rows = None
        if rows is None:
            rows = cached.get(name)
        if rows is not None:
            out[name] = [{k: p.get(k) for k in ("file", "name", "source", "notes", "obs_dim",
                                                 "architecture", "uploaded", "runnable", "active")}
                         for p in rows if p.get("file")]
    if cache and out:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(out, indent=1) + "\n")
        except OSError:
            pass
    return out


def load_policies(proto: Path | None = None, runs: dict | None = None,
                  robot_lists: dict[str, list[dict]] | None = None) -> dict[str, dict]:
    """Every known robot policy file -> source run, robots carrying it,
    transfer-manifest links. Sources: PROTO/linux_control/policies,
    $HEXAPOD_POLICY_DIRS, and the robots' own policy lists."""
    proto = proto or PROTO
    runs = runs if runs is not None else {}
    by_stem = {_stem(r): r for r in runs}

    def resolve(src: str | None) -> str | None:
        return by_stem.get(_stem(src)) if src else None

    pols: dict[str, dict] = {}
    for pdir in [proto / POLICIES_DIR, *EXTRA_POLICY_DIRS]:
        for f in sorted(pdir.glob("*.json")) if pdir.is_dir() else []:
            try:
                d = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            meta = d.get("meta") or {}
            src = meta.get("source") or (d.get("provenance") or {}).get("source") or ""
            run = meta.get("source_run") or resolve(src)
            p = pols.setdefault(f.name, _blank_policy(f.name))
            p.update({
                "kind": d.get("kind") or meta.get("architecture") or "?",
                "source_checkpoint": src or None,
                "run": run,
                "track": runs.get(run, {}).get("track") if run else None,
                "training_hz": meta.get("training_hz") or meta.get("control_hz"),
                "obs_dim": meta.get("obs_dim"),
                "notes": first_sentence(meta.get("notes"), 200) or None,
            })
    for robot, rows in (robot_lists or {}).items():
        for row in rows:
            p = pols.setdefault(row["file"], _blank_policy(row["file"]))
            p["on_robots"].append(robot + (" (active)" if row.get("active") else ""))
            if not p["run"] and row.get("source"):
                p["source_checkpoint"] = p["source_checkpoint"] or row["source"]
                p["run"] = resolve(row["source"])
                p["track"] = runs.get(p["run"], {}).get("track") if p["run"] else None
            p["kind"] = p["kind"] if p["kind"] != "?" else (row.get("architecture") or "?")
            p["obs_dim"] = p["obs_dim"] or row.get("obs_dim")
            p["notes"] = p["notes"] or first_sentence(row.get("notes"), 200) or None
    tdir = proto / TRACK_DOCS_DIR
    for mf in sorted(tdir.rglob("transfer_manifest.json")) if tdir.is_dir() else []:
        try:
            m = json.loads(mf.read_text())
        except (OSError, ValueError):
            continue
        rel = str(mf.relative_to(proto))
        for c in m.get("components") or []:
            exp = c.get("exported_np_policy")
            if not exp:
                continue
            name = Path(exp).name
            p = pols.setdefault(name, _blank_policy(name))
            if not p["run"] and c.get("controller"):
                p["source_checkpoint"] = p["source_checkpoint"] or c["controller"]
                p["run"] = resolve(c["controller"])
                p["track"] = runs.get(p["run"], {}).get("track") if p["run"] else None
            p["manifests"].append({"path": rel, "candidate": m.get("candidate_name"),
                                   "goal": m.get("parent_goal")})
    return pols


# ------------------------------------------------------------ real walks
_LEG_FIELDS = ("label", "seconds", "cmd_v", "commanded_speed_mm_s", "mean_speed_mm_s",
               "straight_speed_mm_s", "speed_ratio", "path_mm", "straight_mm",
               "heading_change_deg", "commanded_turn_deg", "lateral_drift_mm",
               "tilt_max_deg", "current_mean_a", "stop_reason")


def _lab_plans(db: Path | None = None) -> dict[str, dict]:
    """Lab v2 registry: run dir id -> plan title / run status (best effort)."""
    db = LAB2_DB if db is None else db
    if not db.is_file():
        return {}
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        rows = con.execute("select r.id, r.status, p.title, p.status_note from runs r "
                           "join plans p on p.id = r.plan_id").fetchall()
        con.close()
    except sqlite3.Error:
        return {}
    return {r[0]: {"status": r[1], "title": r[2], "note": r[3]} for r in rows}


def load_real_walks(dirs=None, plans: dict | None = None) -> list[dict]:
    """One row per RL drive leg on the real robot, from every lab run folder.

    Sessions are deduplicated on session.json `id` (the Lab registry imports
    the same folder the lab service wrote). Scripted legs (no `policy`) are
    skipped: they are not RL experiments."""
    dirs = LAB_RUNS_DIRS if dirs is None else dirs
    plans = _lab_plans() if plans is None else plans
    seen: set[str] = set()
    rows: list[dict] = []
    for base in dirs:
        base = Path(base)
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            sj, wj = d / "session.json", d / "walk_summary.json"
            if not sj.is_file() or not wj.is_file():
                continue
            try:
                s = json.loads(sj.read_text())
                w = json.loads(wj.read_text())
            except (OSError, ValueError):
                continue
            sid = str(s.get("id") or d.name)
            if sid in seen:
                continue
            seen.add(sid)
            plan = plans.get(d.name) or {}
            for i, leg in enumerate(w.get("legs") or []):
                pol = leg.get("policy")
                if not pol:
                    mode = str(leg.get("mode") or "")
                    pol = mode[3:] if mode.startswith("RL:") else None
                if not pol or not leg.get("seconds"):
                    continue
                row = {"session": sid, "leg": i, "robot": s.get("robot") or w.get("robot"),
                       "when": s.get("created_iso"), "agent": s.get("agent"),
                       "purpose": first_sentence(s.get("purpose"), 160),
                       "lab_title": plan.get("title"), "lab_status": plan.get("status"),
                       "policy": pol, "dir": str(d)}
                for k in _LEG_FIELDS:
                    if k in leg:
                        row[k] = leg[k]
                rows.append(row)
    rows.sort(key=lambda r: (r.get("when") or "", r["session"], r["leg"]))
    return rows


_SWEEP_DIR_RE = re.compile(r"^(\d{8})_(\d{4})_(.+?)_(hexapod\d)$")


def _rms(vals):
    vals = [float(v) for v in vals if isinstance(v, (int, float))]
    return round((sum(v * v for v in vals) / len(vals)) ** 0.5, 2) if vals else None


def load_sweeps(dirs=None) -> list[dict]:
    """The older harness folders (`YYYYMMDD_HHMM_<name>_<robot>/`, written by
    ~/.hexapod/gait_sweep*.py and dr_sweep.py before the lab service): one
    row per RL policy exposure with IMU roll/pitch RMS, tag speed and the
    harness's own verdict. `gaits.json` (per-gait summary) is preferred;
    otherwise `results.json` trials are reduced from their samples."""
    dirs = LAB_RUNS_DIRS if dirs is None else dirs
    rows: list[dict] = []
    for base in dirs:
        base = Path(base)
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            m = _SWEEP_DIR_RE.match(d.name)
            if not m:
                continue
            when = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}T{m.group(2)[:2]}:{m.group(2)[2:]}"
            common = {"session": d.name, "robot": m.group(4), "when": when, "harness": m.group(3),
                      "dir": str(d)}
            gj, rj = d / "gaits.json", d / "results.json"
            if gj.is_file():
                try:
                    gaits = json.loads(gj.read_text())
                except (OSError, ValueError):
                    gaits = []
                for g in gaits if isinstance(gaits, list) else []:
                    if g.get("controller") not in (None, "rl") or not g.get("file"):
                        continue
                    met = g.get("metrics") or {}
                    rows.append({**common, "policy": g["file"], "gait": g.get("gait"),
                                 "exposures": g.get("exposures"), "vx_mps": met.get("vx_mps"),
                                 "roll_rms_deg": met.get("roll_rms_deg"), "roll_peak_deg": met.get("roll_peak_deg"),
                                 "pitch_rms_deg": met.get("pitch_rms_deg"), "max_current_a": met.get("max_current_a"),
                                 "chassis_speed_mm_s": met.get("chassis_speed_mm_s"),
                                 "abs_heading_change_deg": met.get("abs_heading_change_deg"),
                                 "loop_hz": met.get("loop_hz"), "verdict": g.get("verdict"),
                                 "note": first_sentence(g.get("note"), 200) or None})
                continue
            if rj.is_file():
                try:
                    res = json.loads(rj.read_text())
                except (OSError, ValueError):
                    continue
                for t in (res.get("trials") or []) if isinstance(res, dict) else []:
                    if not t.get("file"):
                        continue
                    eng = [x for x in (t.get("samples") or []) if x.get("engaged")]
                    if len(eng) < 2:
                        continue          # never engaged: nothing was measured
                    rows.append({**common, "policy": t["file"], "gait": t.get("arm"),
                                 "exposures": 1, "vx_mps": t.get("vx", res.get("vx")),
                                 "roll_rms_deg": _rms(x.get("roll") for x in eng),
                                 "roll_peak_deg": max((abs(x["roll"]) for x in eng
                                                       if isinstance(x.get("roll"), (int, float))), default=None),
                                 "pitch_rms_deg": _rms(x.get("pitch") for x in eng),
                                 "max_current_a": max((x["maxI"] for x in eng
                                                       if isinstance(x.get("maxI"), (int, float))), default=None),
                                 "chassis_speed_mm_s": None, "abs_heading_change_deg": None,
                                 "loop_hz": _median(x.get("loop_hz") for x in eng),
                                 "engaged_s": round(eng[-1]["t"] - eng[0]["t"], 1) if len(eng) > 1 else None,
                                 "verdict": None, "note": None})
    rows.sort(key=lambda r: (r["when"], r["session"]))
    return rows


def _median(vals):
    vals = [float(v) for v in vals if isinstance(v, (int, float))]
    return round(statistics.median(vals), 3) if vals else None


def summarise_real(rows: list[dict], sweeps: list[dict] | None = None) -> dict[str, dict]:
    """Per-policy aggregate of the real drive legs (lab service) and the
    older sweep exposures (IMU roll/pitch RMS)."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["policy"]].append(r)
    sw: dict[str, list[dict]] = defaultdict(list)
    for r in sweeps or []:
        sw[r["policy"]].append(r)
    out = {}
    for pol in set(by) | set(sw):
        legs, exps = by.get(pol, []), sw.get(pol, [])
        whens = sorted(x.get("when") or "" for x in legs + exps)
        out[pol] = {
            "legs": len(legs),
            "sessions": len({x["session"] for x in legs}),
            "sweep_exposures": sum(int(x.get("exposures") or 1) for x in exps),
            "sweep_sessions": len({x["session"] for x in exps}),
            "robots": sorted({str(x.get("robot")) for x in legs + exps}),
            "first": whens[0] or None, "last": whens[-1] or None,
            "roll_rms_deg_med": _median(x.get("roll_rms_deg") for x in exps),
            "pitch_rms_deg_med": _median(x.get("pitch_rms_deg") for x in exps),
            "sweep_speed_mm_s_med": _median(x.get("chassis_speed_mm_s") for x in exps),
            "sweep_verdicts": dict(Counter(str(x.get("verdict")) for x in exps if x.get("verdict"))),
            "speed_ratio_med": _median(x.get("speed_ratio") for x in legs),
            "straight_speed_mm_s_med": _median(x.get("straight_speed_mm_s") for x in legs),
            "mean_speed_mm_s_med": _median(x.get("mean_speed_mm_s") for x in legs),
            "commanded_speed_mm_s_med": _median(x.get("commanded_speed_mm_s") for x in legs),
            "tilt_max_deg_med": _median(x.get("tilt_max_deg") for x in legs),
            "heading_change_deg_med": _median(abs(x["heading_change_deg"]) for x in legs
                                              if isinstance(x.get("heading_change_deg"), (int, float))),
            "current_mean_a_med": _median(x.get("current_mean_a") for x in legs),
            "stop_reasons": dict(Counter(str(x.get("stop_reason")) for x in legs)),
        }
    return out


# ------------------------------------------------------------ promising
def walk_rank(rw: dict) -> tuple:
    """Sort key for real-world evidence, SMOOTHNESS first (the campaign goal
    is a smooth walk, not a fast one): (1) policies whose drive legs reach
    >= MIN_WALKING_RATIO of the commanded speed, lowest median tilt first,
    speed_ratio as tiebreaker; (2) policies that barely move, by tilt;
    (3) sweep-only evidence (no drive legs), lowest IMU roll RMS first. A
    'poor' harness verdict sinks a policy to the end of its group."""
    ratio = rw.get("speed_ratio_med")
    if rw.get("legs"):
        group = 0 if (ratio or 0) >= MIN_WALKING_RATIO else 1
        smooth = rw.get("tilt_max_deg_med")
    else:
        group = 2
        smooth = rw.get("roll_rms_deg_med")
    poor = 1 if (rw.get("sweep_verdicts") or {}).get("poor") else 0
    return (group, poor, smooth if smooth is not None else 999.0, -(ratio or 0.0),
            -(rw.get("legs", 0) + rw.get("sweep_exposures", 0)))


def promising(runs: dict, policies: dict, real: dict, track: str = "",
              per_track: int = 5) -> dict:
    """Three tiers, best evidence first. Tier 1 = walked on the real robot,
    ordered by walk_rank (smoothness first among policies that actually
    walk); tier 2 = exported for the robot, not walked; tier 3 = sim
    PASS/PARTIAL at acquisition/hardening, never exported."""
    def run_row(r):
        return {k: r.get(k) for k in ("run", "track", "phase", "outcome",
                                      "hardware_ready", "created", "steps", "verdict")}
    walked, exported = [], []
    for name, p in policies.items():
        if track and p.get("track") and p["track"] != track:
            continue
        agg = real.get(name)
        item = {"policy": name, "run": p.get("run"), "track": p.get("track"),
                "training_hz": p.get("training_hz"), "on_robots": p.get("on_robots") or [],
                "sim": run_row(runs[p["run"]]) if p.get("run") in runs else None,
                "manifests": [m["candidate"] or m["path"] for m in p.get("manifests", [])]}
        if agg:
            walked.append({**item, "real": agg})
        else:
            exported.append(item)
    walked.sort(key=lambda x: walk_rank(x["real"]))
    exported.sort(key=lambda x: (x["sim"] or {}).get("created") or "", reverse=True)
    exported_runs = {p.get("run") for p in policies.values()}
    sim_by_track: dict[str, list] = defaultdict(list)
    for r in sorted(runs.values(), key=lambda r: r.get("created") or "", reverse=True):
        if track and r["track"] != track:
            continue
        if r["outcome"] in POSITIVE and r.get("phase") in ("acquisition", "hardening") \
                and r["run"] not in exported_runs and r["hardware_ready"] is not False:
            if len(sim_by_track[r["track"]]) < per_track:
                sim_by_track[r["track"]].append(run_row(r))
    by_track = {}
    for tr in sorted({r["track"] for r in runs.values()}):
        if track and tr != track:
            continue
        rs = [r for r in runs.values() if r["track"] == tr]
        last_pass = max((r for r in rs if r["outcome"] in POSITIVE),
                        key=lambda r: r.get("created") or "", default=None)
        by_track[tr] = {"runs": len(rs), "outcomes": dict(Counter(r["outcome"] for r in rs)),
                        "last_run": max((r.get("created") or "" for r in rs), default=None),
                        "last_pass": run_row(last_pass) if last_pass else None,
                        "walked_policies": sorted(p["policy"] for p in walked
                                                  if p.get("track") == tr)}
    return {"walked_on_robot": walked, "exported_not_walked": exported,
            "sim_pass_not_exported": dict(sim_by_track), "by_track": by_track}


# ------------------------------------------------------------ story
_BOOKKEEPING_FLAGS = ("--cfg-set", "--notes", "--out-name", "--run-name")


def story(run: str, runs: dict, entries: list[dict] | None = None,
          policies: dict | None = None, real_rows: list[dict] | None = None,
          sweeps: list[dict] | None = None) -> dict:
    """Everything the records hold about one run, joined."""
    if run not in runs:
        raise KeyError(run)
    r = runs[run]
    entries = entries if entries is not None else state_dir.load_ledger()
    current = current_entries(entries)
    e = current.get(run, {})
    cfg, flags = parse_args_list(e.get("extra_args"))
    diff = None
    if r["parent"] and r["parent"] in current:
        pcfg, pflags = parse_args_list(current[r["parent"]].get("extra_args"))
        diff = {"cfg_changed": {k: [pcfg.get(k), v] for k, v in cfg.items() if pcfg.get(k) != v},
                "cfg_dropped": {k: v for k, v in pcfg.items() if k not in cfg},
                "flags_changed": {k: [pflags.get(k), v] for k, v in flags.items()
                                  if pflags.get(k) != v and k not in _BOOKKEEPING_FLAGS}}
    pols = [p for p in (policies or {}).values() if p.get("run") == run]
    names = {p["policy"] for p in pols}
    legs = [x for x in (real_rows or []) if x["policy"] in names]
    exps = [x for x in (sweeps or []) if x["policy"] in names]
    agg = summarise_real(legs, exps)
    return {
        **{k: r[k] for k in ("run", "track", "phase", "scope", "created", "steps", "seed",
                             "status", "outcome", "hardware_ready", "wandb_id", "pod",
                             "checkpoint", "parent", "parent_raw", "root", "ancestors",
                             "children")},
        "attempts": sum(1 for x in entries if x.get("run") == run),
        "wandb_url": WANDB_RUN_URL.format(id=r["wandb_id"]) if r.get("wandb_id") else None,
        "hypothesis": e.get("hypothesis"), "gate": e.get("gate"), "verdict": e.get("verdict"),
        "lineage": [{"run": a, "outcome": runs[a]["outcome"], "phase": runs[a]["phase"],
                     "created": (runs[a]["created"] or "")[:10]} for a in r["ancestors"]],
        "children_outcomes": {c: runs[c]["outcome"] for c in r["children"]},
        "diff_vs_parent": diff,
        "n_cfg_keys": len(cfg), "flags": {k: v for k, v in flags.items() if k not in _BOOKKEEPING_FLAGS},
        "exports": pols,
        "real_walks": {k: v for k, v in agg.items()} or None,
        "real_legs_recent": legs[-5:],
        "real_sweeps_recent": exps[-5:],
        "story_doc": f"rl_docs/runs/{run}.md",
    }


def story_md(s: dict) -> str:
    o = [f"# {s['run']} — {s['outcome']} ({s['status']})", ""]
    o.append(f"- track {s['track']} · phase {s['phase']} · scope {s['scope']} · created "
             f"{(s['created'] or '')[:16]} · steps {s['steps']} · seed {s['seed']} · pod {s['pod']}")
    o.append(f"- hardware_ready: {s['hardware_ready']} · attempts: {s['attempts']} · W&B: "
             f"{s['wandb_url'] or '-'}")
    o.append(f"- story doc: {s['story_doc']} · checkpoint: {s['checkpoint'] or 'ppo_goal_' + _stem(s['run']) + '.zip (by name)'}")
    o += ["", "## Lineage (nearest parent first)"]
    if s["lineage"]:
        for a in s["lineage"]:
            o.append(f"- {a['run']} — {a['outcome']} ({a['phase']}, {a['created']})")
    else:
        o.append(f"- (root of its lineage{'; parent ' + s['parent_raw'] if s['parent_raw'] else ''})")
    if s["diff_vs_parent"]:
        d = s["diff_vs_parent"]
        o += ["", f"## What changed vs parent {s['parent']}"]
        for k, (a, b) in sorted(d["cfg_changed"].items()):
            o.append(f"- cfg {k}: {a} -> {b}")
        for k, v in sorted(d["cfg_dropped"].items()):
            o.append(f"- cfg {k}: {v} -> (dropped)")
        for k, (a, b) in sorted(d["flags_changed"].items()):
            o.append(f"- {k}: {a} -> {b}")
        if not (d["cfg_changed"] or d["cfg_dropped"] or d["flags_changed"]):
            o.append("- identical launch args (seed/continuation only)")
    o += ["", "## Hypothesis", s["hypothesis"] or "(none)", "", "## Gate", s["gate"] or "(none)",
          "", "## Verdict", s["verdict"] or "(none yet)"]
    if s["children_outcomes"]:
        o += ["", "## Children"]
        for c, oc in sorted(s["children_outcomes"].items()):
            o.append(f"- {c} — {oc}")
    o += ["", "## Real robot"]
    if s["exports"]:
        for p in s["exports"]:
            man = ", ".join(m["candidate"] or m["path"] for m in p["manifests"]) or "-"
            robots = ", ".join(p.get("on_robots") or []) or "not on any robot's policy list"
            o.append(f"- exported as {p['policy']} ({p['training_hz'] or '?'} Hz); on robots: {robots}; "
                     f"manifests: {man}")
    else:
        o.append("- never exported to a robot policy file")
    for pol, rw in (s["real_walks"] or {}).items():
        o.append(_real_line(pol, rw))
    for x in s["real_legs_recent"]:
        o.append(f"  - {(x.get('when') or '')[:16]} {x.get('robot')} {x.get('label')}: "
                 f"ratio {x.get('speed_ratio')}, tilt {x.get('tilt_max_deg')}, stop {x.get('stop_reason')} "
                 f"[{x.get('lab_title') or x.get('purpose') or x['session']}]")
    for x in s["real_sweeps_recent"]:
        o.append(f"  - {x['when']} {x['robot']} {x['harness']} {x.get('gait') or ''}: roll rms {x.get('roll_rms_deg')} "
                 f"pitch rms {x.get('pitch_rms_deg')} speed {x.get('chassis_speed_mm_s')} mm/s "
                 f"verdict {x.get('verdict')} [{x['session']}]")
    if s["exports"] and not s["real_walks"]:
        o.append("- exported but no real drive leg or sweep exposure recorded under this policy name")
    return "\n".join(o)


def _real_line(pol: str, rw: dict) -> str:
    parts = [f"- {pol}: on {', '.join(rw['robots'])} {(rw['first'] or '')[:10]}..{(rw['last'] or '')[:10]}"]
    if rw["legs"]:
        parts.append(f"{rw['legs']} drive legs / {rw['sessions']} sessions: speed_ratio med "
                     f"{_fmt_ratio(rw['speed_ratio_med'])}, straight {rw['straight_speed_mm_s_med']} of "
                     f"{rw['commanded_speed_mm_s_med']} mm/s commanded, tilt max med {rw['tilt_max_deg_med']} deg, "
                     f"|heading change| med {rw['heading_change_deg_med']} deg, stops {rw['stop_reasons']}")
    if rw["sweep_exposures"]:
        parts.append(f"{rw['sweep_exposures']} sweep exposures / {rw['sweep_sessions']} sessions: roll rms med "
                     f"{rw['roll_rms_deg_med']} deg, pitch rms med {rw['pitch_rms_deg_med']} deg, tag speed med "
                     f"{rw['sweep_speed_mm_s_med']} mm/s, harness verdicts {rw['sweep_verdicts']}")
    return "; ".join(parts)


# ------------------------------------------------------------ journals
def open_questions(path: Path | None = None) -> list[dict]:
    """OPERATOR_QUESTIONS.md `## <id> — OPEN` headers with their lead lines."""
    path = path or (state_dir.STATE_DIR / "OPERATOR_QUESTIONS.md")
    if not path.is_file():
        return []
    out, cur = [], None
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("## "):
            head = line[3:].strip()
            is_open = bool(re.search(r"\bOPEN\b", head))
            cur = {"id": head.split(" — ")[0].split(" - ")[0][:80], "state": "OPEN", "lead": []} if is_open else None
            if cur:
                out.append(cur)
            continue
        if cur is not None and line.strip() and len(cur["lead"]) < 3 and not line.startswith("#"):
            cur["lead"].append(line.strip())
    return out


# ------------------------------------------------------------ build
def default_index_dir() -> Path:
    env = os.environ.get("HEXAPOD_RL_INDEX_DIR")
    if env:
        return Path(env).expanduser()
    shared = Path.home() / ".hexapod"
    if (shared / "lab_runs").is_dir():        # the Mac (has the Robot Lab folders): keep the index
        return shared / "rl_index"            # outside .state, which state_sync.sh pull swaps whole
    return state_dir.STATE_DIR / "index"      # the controller (mirrored to the PVC by state_sync push)


def _fmt_ratio(x):
    return "-" if x is None else f"{x:.2f}"


def index_md(meta: dict, runs: dict, pols: dict, real: dict, prom: dict,
             status_map: dict, questions: list[dict]) -> str:
    oc = Counter(r["outcome"] for r in runs.values())
    o = ["# RL campaign index — start here", "",
         f"Built {meta['built_at']} from ledger fingerprint {meta['ledger_fingerprint'][:12]} "
         f"({meta['ledger_entries']} entries, {meta['runs']} runs, {meta['tracks']} tracks). "
         f"Real-world sources: {', '.join(meta['real_sources']) or 'none reachable from here'} "
         f"({meta['real_legs']} RL drive legs in {meta['real_sessions']} sessions).", "",
         "Everything here is DERIVED from the ledger, the exported policy files and the Robot Lab "
         "run folders; nothing is hand-edited. Rebuild: `ops.sh index build`. Query one run: "
         "`ops.sh index story <run>` (lineage, what changed vs parent, hypothesis/gate/verdict, "
         "exports, real walks). The raw `status` strings are collapsed to one vocabulary in "
         "status_map.json; `outcome` is what to filter on.", "",
         "## 1. Policies that have walked on the real robot (best real-world evidence first)", "",
         "Drive legs come from lab-service sessions (speed_ratio = straight-line speed achieved / "
         "commanded, 1.0 = walks as commanded; tilt max = per-leg IMU tilt peak). Sweep exposures come "
         "from the older gait/DR harnesses (IMU roll RMS in degrees, lower is smoother). Medians over "
         f"everything recorded. ORDER: smoothness first -- policies whose legs reach >= {MIN_WALKING_RATIO:.2f} "
         "of the commanded speed, lowest tilt first (speed as tiebreaker); then policies that barely move; "
         "then sweep-only evidence by roll RMS; a 'poor' harness verdict sinks a row within its group.", "",
         "| policy | source run (sim outcome) | track | drive legs / sessions | speed_ratio | straight mm/s | "
         "tilt max deg | sweep exposures | roll rms deg | harness verdicts | robots | last |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for w in prom["walked_on_robot"]:
        rw = w["real"]; sim = w["sim"] or {}
        o.append(f"| {w['policy']} | {w['run'] or '?'} ({sim.get('outcome', '?')}) | {w['track'] or '?'} | "
                 f"{rw['legs']} / {rw['sessions']} | {_fmt_ratio(rw['speed_ratio_med'])} | "
                 f"{rw['straight_speed_mm_s_med'] if rw['straight_speed_mm_s_med'] is not None else '-'} | "
                 f"{rw['tilt_max_deg_med'] if rw['tilt_max_deg_med'] is not None else '-'} | "
                 f"{rw['sweep_exposures']} | {rw['roll_rms_deg_med'] if rw['roll_rms_deg_med'] is not None else '-'} | "
                 f"{', '.join(f'{k} {v}' for k, v in rw['sweep_verdicts'].items()) or '-'} | "
                 f"{', '.join(rw['robots'])} | {(rw['last'] or '')[:10]} |")
    if not prom["walked_on_robot"]:
        o.append("| (no real RL drive legs found from this machine) | | | | | | | | | | | |")
    o += ["", "## 2. Exported for the robot, not yet walked", "",
          "| policy | source run | track | sim outcome | phase | hz | on robots | manifests |",
          "|---|---|---|---|---|---|---|---|"]
    for x in prom["exported_not_walked"]:
        sim = x["sim"] or {}
        o.append(f"| {x['policy']} | {x['run'] or '?'} | {x['track'] or '?'} | {sim.get('outcome', '?')} | "
                 f"{sim.get('phase') or '?'} | {x['training_hz'] or '?'} | {', '.join(x['on_robots']) or '-'} | "
                 f"{', '.join(x['manifests']) or '-'} |")
    o += ["", "## 3. Sim PASS/PARTIAL at acquisition or hardening, never exported (newest per track)", ""]
    for tr, items in sorted(prom["sim_pass_not_exported"].items()):
        o.append(f"**{tr}**")
        for it in items:
            o.append(f"- {it['run']} — {it['outcome']} ({it['phase']}, {(it['created'] or '')[:10]}, "
                     f"hw_ready {it['hardware_ready']}): {it['verdict'] or ''}")
        o.append("")
    o += ["## 4. Tracks", "", "| track | runs | PASS | PARTIAL | FAIL | canary pass/fail | refused/crashed/killed | last run | last PASS |",
          "|---|---|---|---|---|---|---|---|---|"]
    for tr, t in prom["by_track"].items():
        c = t["outcomes"]
        o.append(f"| {tr} | {t['runs']} | {c.get('PASS', 0)} | {c.get('PARTIAL', 0)} | {c.get('FAIL', 0)} | "
                 f"{c.get('CANARY_PASS', 0)}/{c.get('CANARY_FAIL', 0)} | "
                 f"{c.get('REFUSED', 0)}/{c.get('CRASHED', 0)}/{c.get('KILLED', 0)} | {(t['last_run'] or '')[:10]} | "
                 f"{(t['last_pass'] or {}).get('run', '-')} |")
    o += ["", "## 5. Outcome vocabulary (all runs)", ""]
    o += [f"- {k}: {oc.get(k, 0)} — {v}" for k, v in OUTCOMES.items() if oc.get(k)]
    o += ["", f"{len(status_map)} raw status spellings collapse to {len([k for k in OUTCOMES if oc.get(k)])} outcomes; "
          "mapping with counts in status_map.json.", "",
          f"## 6. Open operator questions: {len(questions)}", "",
          "Listed with their lead lines in open_questions.md (derived from OPERATOR_QUESTIONS.md).", "",
          "## By topic and by gait", "",
          "topics/INDEX.md — every RL run and Robot Lab experiment tagged by skill (stand/rise/hold/lower, walk, "
          "turn, joystick, speed, robustness, sim2real, current, lifecycle), by method (bc-teacher, amp, cpg, rl-only, "
          "architecture, exploration, curriculum, reward) and by lab activity (sysid, instrumentation, endurance, "
          "scripted-gait); one page per topic with the lineages tried, the lab experiments and every run. "
          "topics/gaits.md — every policy file with its training lineage and real-robot trials. "
          "`ops.sh index topic <id>` / `ops.sh index gait <policy|run>` print them.", "",
          "## Files", "",
          "- runs.jsonl — one row per run (current attempt): track, phase, outcome, parent, children, "
          "ancestors, root, hardware_ready, wandb_id, first sentence of hypothesis and verdict",
          "- lineage.json — run -> parent, children, root, depth",
          "- policies.json — exported policy -> source run, manifests, real-walk aggregate",
          "- real_walks.jsonl — one row per RL drive leg on the real robot",
          "- promising.json — the three tiers above as data",
          "- status_map.json — raw status -> outcome, with counts",
          "- open_questions.md, meta.json"]
    return "\n".join(o) + "\n"


def build(out: Path | None = None, with_real: bool = True, proto: Path | None = None,
          fresh: bool = False) -> dict:
    out = out or default_index_dir()
    out.mkdir(parents=True, exist_ok=True)
    entries = state_dir.load_ledger()
    runs = load_runs(entries)
    robot_lists = robot_policy_lists(cache=out / "robot_policies.json",
                                     ttl_s=0.0 if fresh else ROBOT_CACHE_TTL_S) if with_real else {}
    pols = load_policies(proto, runs, robot_lists)
    real_rows = load_real_walks() if with_real else []
    sweeps = load_sweeps() if with_real else []
    real = summarise_real(real_rows, sweeps)
    for name, agg in real.items():
        pols.setdefault(name, _blank_policy(name))["real"] = agg
    prom = promising(runs, pols, real)
    status_map: dict[str, dict] = {}
    for e in current_entries(entries).values():
        raw = str(e.get("status"))
        s = status_map.setdefault(raw, {"outcome": outcome(e), "count": 0})
        s["count"] += 1
    questions = open_questions()
    real_sources = [str(d) for d in LAB_RUNS_DIRS if d.is_dir()] if with_real else []
    meta = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ledger_fingerprint": state_dir.ledger_fingerprint(),
            "ledger_entries": len(entries), "runs": len(runs),
            "tracks": len({r["track"] for r in runs.values()}),
            "policies": len(pols), "real_sources": real_sources,
            "robots_listed": sorted(robot_lists),
            "real_legs": len(real_rows), "real_sessions": len({r["session"] for r in real_rows}),
            "sweep_exposures": len(sweeps), "sweep_sessions": len({r["session"] for r in sweeps}),
            "open_questions": len(questions),
            "outcomes": dict(Counter(r["outcome"] for r in runs.values()))}

    def dump(name, obj):
        (out / name).write_text(json.dumps(obj, indent=1, default=str, sort_keys=False) + "\n")
    with (out / "runs.jsonl").open("w") as fh:
        for r in sorted(runs.values(), key=lambda r: r.get("created") or ""):
            fh.write(json.dumps(r, default=str) + "\n")
    with (out / "real_walks.jsonl").open("w") as fh:
        for r in real_rows:
            fh.write(json.dumps(r, default=str) + "\n")
    with (out / "real_sweeps.jsonl").open("w") as fh:
        for r in sweeps:
            fh.write(json.dumps(r, default=str) + "\n")
    dump("lineage.json", {r["run"]: {"parent": r["parent"], "children": r["children"],
                                     "root": r["root"], "depth": len(r["ancestors"])}
                          for r in runs.values()})
    dump("policies.json", pols)
    dump("promising.json", prom)
    dump("status_map.json", dict(sorted(status_map.items(), key=lambda kv: -kv[1]["count"])))
    dump("meta.json", meta)
    (out / "open_questions.md").write_text(
        "# Open operator questions (derived from OPERATOR_QUESTIONS.md)\n\n" +
        "".join(f"## {q['id']}\n" + "\n".join(q["lead"]) + "\n\n" for q in questions))
    (out / "INDEX.md").write_text(index_md(meta, runs, pols, real, prom, status_map, questions))
    try:
        import rl_topics
        meta["topics"] = rl_topics.build(out, runs, entries, pols, real)
    except Exception as e:  # the topic pages are a view; never fail the build over them
        meta["topics"] = {"error": repr(e)}
    meta["out"] = str(out)
    return meta


# ------------------------------------------------------------ CLI
def _load_all(with_real=True):
    entries = state_dir.load_ledger()
    runs = load_runs(entries)
    robot_lists = robot_policy_lists(cache=default_index_dir() / "robot_policies.json") if with_real else {}
    pols = load_policies(None, runs, robot_lists)
    rows = load_real_walks() if with_real else []
    sweeps = load_sweeps() if with_real else []
    for name, agg in summarise_real(rows, sweeps).items():
        pols.setdefault(name, _blank_policy(name))["real"] = agg
    return entries, runs, pols, rows, sweeps


def promising_md(prom: dict, limit: int = 20) -> str:
    o = ["## Walked on the real robot (smoothest walking policy first: legs reaching >= "
         f"{MIN_WALKING_RATIO:.2f} of commanded speed by lowest tilt, then barely-moving, then sweep-only)"]
    for w in prom["walked_on_robot"][:limit]:
        rw, sim = w["real"], w["sim"] or {}
        o.append(f"- {w['policy']} <- {w['run']} [{w['track']}, sim {sim.get('outcome')}]: "
                 f"{rw['legs']} legs/{rw['sessions']} sessions, speed_ratio {_fmt_ratio(rw['speed_ratio_med'])}, "
                 f"straight {rw['straight_speed_mm_s_med']} mm/s, tilt {rw['tilt_max_deg_med']} deg, last {(rw['last'] or '')[:10]}")
    o.append("\n## Exported, not yet walked")
    for x in prom["exported_not_walked"][:limit]:
        sim = x["sim"] or {}
        o.append(f"- {x['policy']} <- {x['run']} [{x['track']}, sim {sim.get('outcome')} {sim.get('phase')}] "
                 f"{', '.join(x['manifests']) or ''}")
    o.append("\n## Sim PASS/PARTIAL (acquisition/hardening), not exported")
    for tr, items in sorted(prom["sim_pass_not_exported"].items()):
        for it in items[:limit]:
            o.append(f"- [{tr}] {it['run']} — {it['outcome']} ({it['phase']}, {(it['created'] or '')[:10]}): {it['verdict'] or ''}")
    return "\n".join(o)


def real_md(rows: list[dict], key: str = "", limit: int = 50, pols: dict | None = None,
            sweeps: list[dict] | None = None) -> str:
    sweeps = sweeps or []
    if key:
        names = {key}
        if pols:
            names |= {p["policy"] for p in pols.values() if p.get("run") == key}
        rows = [r for r in rows if r["policy"] in names or key in r["policy"]]
        sweeps = [r for r in sweeps if r["policy"] in names or key in r["policy"]]
    agg = summarise_real(rows, sweeps)
    o = [f"{len(rows)} RL drive legs in {len({r['session'] for r in rows})} lab sessions + "
         f"{len(sweeps)} sweep exposures in {len({r['session'] for r in sweeps})} harness runs, "
         f"{len(agg)} policies" + (f" matching {key!r}" if key else "")]
    for pol, a in sorted(agg.items(), key=lambda kv: -(kv[1]["speed_ratio_med"] or 0)):
        src = (pols or {}).get(pol, {}).get("run")
        o.append(f"\n## {pol}" + (f" <- {src}" if src else " (no ledger run resolved)"))
        o.append(_real_line(pol, a)[2:])
    if sweeps:
        o.append("\n## Sweep exposures (newest last)")
        for r in sweeps[-limit:]:
            o.append(f"- {r['when']} {r['robot']} {r['harness']} {r['policy']} {r.get('gait') or ''}: "
                     f"roll rms {r.get('roll_rms_deg')} pitch rms {r.get('pitch_rms_deg')} speed "
                     f"{r.get('chassis_speed_mm_s')} mm/s maxI {r.get('max_current_a')} verdict {r.get('verdict')}")
    o.append("\n## Drive legs (newest last)")
    for r in rows[-limit:]:
        o.append(f"- {(r.get('when') or '')[:16]} {r.get('robot')} {r['policy']} {r.get('label')}: cmd {r.get('cmd_v')} "
                 f"ratio {r.get('speed_ratio')} straight {r.get('straight_speed_mm_s')} tilt {r.get('tilt_max_deg')} "
                 f"stop {r.get('stop_reason')} [{r.get('lab_title') or r.get('purpose') or r['session']}]")
    return "\n".join(o)


def lineage_md(run: str, runs: dict) -> str:
    if run not in runs:
        return f"no ledger run named {run!r}"
    r = runs[run]
    o = [f"root: {r['root']}"]
    for a in reversed(r["ancestors"]):
        o.append(f"  {a} — {runs[a]['outcome']} ({runs[a]['phase']}, {(runs[a]['created'] or '')[:10]})")
    o.append(f"* {run} — {r['outcome']} ({r['phase']}, {(r['created'] or '')[:10]})")

    def walk(n, depth):
        for c in runs[n]["children"]:
            o.append("  " * depth + f"  {c} — {runs[c]['outcome']} ({runs[c]['phase']}, {(runs[c]['created'] or '')[:10]})")
            walk(c, depth + 1)
    walk(run, 1)
    return "\n".join(o)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write the index files (default dir: $HEXAPOD_RL_INDEX_DIR, "
                                     "~/.hexapod/rl_index on the Mac, <state>/index on the controller)")
    b.add_argument("--out", type=Path)
    b.add_argument("--no-real", action="store_true", help="skip the Robot Lab run folders")
    b.add_argument("--fresh", action="store_true", help="re-fetch the robots' policy lists now")
    s = sub.add_parser("story", help="one run, everything joined, as markdown")
    s.add_argument("run")
    s.add_argument("--json", action="store_true")
    l = sub.add_parser("lineage", help="ancestors and descendants of a run")
    l.add_argument("run")
    p = sub.add_parser("promising", help="the three evidence tiers")
    p.add_argument("--track", default="")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    r = sub.add_parser("real", help="real-robot RL drive legs, per policy")
    r.add_argument("key", nargs="?", default="", help="policy file name or ledger run")
    r.add_argument("--limit", type=int, default=50)
    sub.add_parser("topics", help="topic table over RL runs + Robot Lab experiments")
    tp = sub.add_parser("topic", help="one topic page: lineages tried, lab experiments, every run")
    tp.add_argument("id", help="topic id, e.g. stand, rise, lower, walk, turn, speed, sim2real")
    sub.add_parser("gaits", help="every gait/policy file: training lineage + real trials")
    gp = sub.add_parser("gait", help="one gait/policy file in full")
    gp.add_argument("key", help="policy file name or training run")
    sub.add_parser("outcomes", help="raw status -> outcome, with counts")
    sub.add_parser("open-questions")
    a = ap.parse_args(argv)

    if a.cmd == "build":
        meta = build(a.out, with_real=not a.no_real, fresh=a.fresh)
        print(json.dumps(meta, indent=1))
        return 0
    if a.cmd == "outcomes":
        entries = state_dir.load_ledger()
        c = Counter((str(e.get("status")), outcome(e)) for e in current_entries(entries).values())
        for (raw, oc), n in sorted(c.items(), key=lambda kv: (kv[0][1], -kv[1])):
            print(f"{n:5}  {oc:18} <- {raw[:90]}")
        return 0
    if a.cmd == "open-questions":
        for q in open_questions():
            print(f"## {q['id']}\n" + "\n".join(q["lead"]) + "\n")
        return 0
    with_real = a.cmd in ("story", "promising", "real", "topics", "topic", "gaits", "gait")
    entries, runs, pols, rows, sweeps = _load_all(with_real)
    if a.cmd in ("topics", "topic", "gaits", "gait"):
        import rl_topics
        d = rl_topics.compute(runs, entries, pols, summarise_real(rows, sweeps))
        if a.cmd == "topics":
            print(rl_topics.index_page(d["run_topics"], d["lab"], runs, d["gaits"]))
        elif a.cmd == "topic":
            if a.id not in rl_topics.TOPIC_BY_ID:
                print(f"unknown topic {a.id!r}; one of {[t['id'] for t in rl_topics.TOPICS]}")
                return 1
            print(rl_topics.topic_page(a.id, runs, d["run_topics"], d["lab"], d["lineage"]))
        elif a.cmd == "gaits":
            print(rl_topics.gaits_page(d["gaits"]))
        else:
            print(rl_topics.gait_page(a.key, d["gaits"], runs, d["lab"], d["lineage"]))
        return 0
    if a.cmd == "story":
        try:
            st = story(a.run, runs, entries, pols, rows, sweeps)
        except KeyError:
            print(f"no ledger run named {a.run!r}")
            return 1
        print(json.dumps(st, indent=1, default=str) if a.json else story_md(st))
    elif a.cmd == "lineage":
        print(lineage_md(a.run, runs))
    elif a.cmd == "promising":
        prom = promising(runs, pols, summarise_real(rows, sweeps), a.track)
        print(json.dumps(prom, indent=1, default=str) if a.json else promising_md(prom, a.limit))
    elif a.cmd == "real":
        print(real_md(rows, a.key, a.limit, pols, sweeps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
