"""rl_topics.py -- one page per SKILL / METHOD / GAIT across the RL ledger AND
the Robot Lab registry, so "every run about standing" or "everything we did
with gait X" is one file, not a grep.

Two record stores never shared a vocabulary: the orchestrator ledger (runs
named `cw-stance50hz-rlonly-...`, hypotheses in prose, cfg keys like
`goal.rise_height_mm`) and the Robot Lab registry (plans titled "RL gait
trial ws800: <policy>.json", "sysid: unloaded hip Bode", protocols like
`champion_stand_ground_v1`). This module tags every item in both with the
same topic ids by explicit keyword rules (TOPICS below -- the rules ARE the
definition, extend them there), groups RL runs into lineages (root run =
one "approach"), and joins gait/policy files to their training lineage and
their real-robot trials.

Outputs (under <index dir>/topics/): INDEX.md, <topic>.md, gaits.md,
topics.json. Built by `rl_index.py build`; queried with
`rl_index.py topics | topic <id> | gaits | gait <policy|run>`.
Nothing here writes to the ledger or the Lab registry.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import rl_index

LAB2_DB = rl_index.LAB2_DB

# ------------------------------------------------------------ topic rules
# stems: matched as substrings of run-name / protocol TOKENS (split on -_/ ., digits
#        stripped), so compound tokens like `walkscratch`, `stance50hz`, `turncap` hit.
# words: regexes over the lowercased prose (hypothesis, gate, title, why, notes).
# cfg:   ledger cfg keys (`--cfg-set k=v`) whose presence tags the run.
# tracks: track ids that tag the run outright.
TOPICS: list[dict] = [
    {"id": "stand", "label": "Stand: rise, hold, lower, stance",
     "what": "getting up from the floor, holding a standing pose, sitting back down; stance-only roles",
     "stems": ["stand", "stance", "rise", "hold", "lower", "tuck", "standheight", "crouch", "sitdown",
               "riseonly", "recover"],
     "words": [r"\brise\b", r"\bstand(?:ing|-up| up)?\b", r"\bstance\b", r"\bsit(?:-down| down)?\b", r"\bget(?:ting)? up\b",
               r"\brise/hold/lower\b"],
     "cfg": ["goal.rise_height_mm", "goal.rise_flat_frac", "goal.rise_rsi_frac", "goal.lower_stage_gate"]},
    {"id": "rise", "label": "Rise (stand up from the floor)", "parent": "stand",
     "stems": ["rise", "riseonly", "standheight", "flatstart", "recover"],
     "words": [r"\brise\b", r"\bstand-?up\b", r"\bflat-start\b", r"\bget(?:ting)? up\b", r"\brise/hold/lower\b"],
     "cfg": ["goal.rise_height_mm", "goal.rise_flat_frac", "goal.rise_rsi_frac"]},
    {"id": "hold", "label": "Hold (stay standing)", "parent": "stand",
     "stems": ["hold", "holdbc", "holdbias", "stance"], "words": [r"\bhold\b(?! the)", r"\brise/hold/lower\b"]},
    {"id": "lower", "label": "Lower / sit down", "parent": "stand",
     "stems": ["lower", "sitdown", "lowerrole", "lowerstall", "lowerstagegate", "postlower"],
     "words": [r"\blower(?:ing)?\b(?! (?:std|bound|lr|learning|entropy|cap|dose|kl))", r"\bsit(?:-down| down)\b",
               r"\brise/hold/lower\b"],
     "cfg": ["goal.lower_stage_gate", "safety.lower_stall_terminate_s"]},
    {"id": "walk", "label": "Walk (translation, any heading)",
     "what": "forward / all-heading walking, gait quality, slip, sacrificed legs",
     "stems": ["walk", "gait", "stride", "allhead", "allheading", "tripod", "walkscratch", "walkteach", "headset",
               "loadslip", "noslip", "walkcurr"],
     "words": [r"\bwalk(?:ing|s|er)?\b", r"\bgait\b"],
     "cfg": ["goal.walk_pure=1", "goal.walk_heading_set"]},
    {"id": "turn", "label": "Turn / yaw",
     "what": "turn-in-place and yaw-rate command following",
     "stems": ["turn", "yaw", "wz", "turncap", "yawcredit", "yawcmd", "walkyaw", "turnpay", "turnfault", "yawbias",
               "wzcart", "wzinit", "wzcurr", "rot"],
     "words": [r"\bturn(?:ing|s)?\b", r"\byaw\b", r"\bwz\b", r"\bturn-in-place\b", r"\brot60\b"],
     "cfg": ["goal.walk_yaw_cmd=1", "goal.walk_turn_in_place_frac", "goal.walk_yaw_max_rad_s"]},
    {"id": "joystick", "label": "Joystick command following",
     "what": "arbitrary vx/vy/wz commands, stop-and-go, command envelopes, joygate sessions",
     "stems": ["joy", "joystick", "stopgo", "joygate", "joyhead", "joyfullcurr", "head"],
     "words": [r"\bjoystick\b", r"\bjoygate\b", r"\bstop-and-go\b", r"\bcommand (?:envelope|following)\b"],
     "cfg": ["goal.walk_cmd_mode"], "tracks": ["joystick"]},
    {"id": "speed", "label": "Speed (faster gait)",
     "stems": ["speed", "ps200", "ps175", "speedhi", "env50dps", "footcatch"],
     "words": [r"\bfaster\b", r"\bspeed track\b", r"\bspeed ladder\b"], "tracks": ["speed"]},
    {"id": "robustness", "label": "Robustness: pushes, faults, tipped starts, payload, tilt",
     "stems": ["recover", "tip", "push", "fault", "kick", "payload", "groundtilt", "comshift", "tipfrac", "pushcont",
               "turnfault", "badstart", "pushcal", "capsev", "capleg", "recoverany", "collapse"],
     "words": [r"\bpush(?:es|ed)?\b", r"\bfault(?:s|y)?\b", r"\btipp?(?:ed|ing)\b", r"\bpayload\b", r"\bground tilt\b",
               r"\bperturb", r"\bdead (?:leg|actuator|servo)\b", r"\bcollapse\b"],
     "cfg": ["dr.fault_prob=0.5", "dr.fault_prob=1.0", "dr.fault_prob=0.7"]},
    {"id": "sim2real", "label": "Sim-to-real: domain randomization, transfer, hardware handoff",
     "stems": ["dr", "ps200dr", "sim2real", "widen", "envwide", "widedr", "massfix", "meshref", "transfer",
               "hardware", "deploy", "bundle", "dep", "safewiden", "drwiden", "realgap", "refit", "twin", "ladder",
               "powercurrent", "frictionasym", "stickslip", "imudrop", "latencymid", "pinrobust"],
     "words": [r"\bdomain random", r"\bsim-?to-?real\b", r"\btransfer\b", r"\bhardware\b", r"\bphysical\b",
               r"\breal robot\b", r"\brobot lab\b", r"\breality[- ]gap\b", r"\bdigital twin\b", r"\bsim-vs-real\b"]},
    {"id": "current", "label": "Servo current, torque and load limits",
     "stems": ["current", "curhot", "currentcap", "cap", "torque", "loadslip", "overcurrent", "headroom",
               "loadeven", "movecur", "stopcur", "torquescale", "desat", "slew", "slewcap", "powercurrent"],
     "words": [r"\bover[_ -]?current\b", r"\bservo current\b", r"\bcurrent (?:cap|trip|limit|model|draw)\b",
               r"\btorque\b", r"\bstall\b", r"\bover[_ -]?load\b", r"\bslew\b", r"\b\d+(?:\.\d+)? ?a\b"]},
    {"id": "lifecycle", "label": "Lifecycle composition: stand -> walk -> lower, role bundles",
     "stems": ["lifecycle", "bundle", "handoff", "hybrid", "composed", "standwalk", "modeseq", "todaypolicy",
               "fullstack", "robotwalk"],
     "words": [r"\blifecycle\b", r"\bcompos(?:ed|ition)\b", r"\bhand-?off\b", r"\bbundle\b", r"\bstate machine\b",
               r"\bmode[_ ]seq\b", r"\bfull[- ]stack\b", r"\bstand->walk\b"],
     "cfg": ["goal.mode_seq"], "tracks": ["todaypolicy"]},
    # -------- methods
    {"id": "bc-teacher", "label": "Method: behaviour cloning / scripted teacher / anchors",
     "stems": ["bc", "dualbc", "teach", "walkteach", "anchor", "distill", "bcgait", "bcchain", "bcinit", "clone",
               "bcanchor", "teacher", "dep"],
     "words": [r"\bbc\b", r"\bbehaviou?r[- ]clon", r"\bteacher\b", r"\bdistill", r"\bbc[- ]anchor\b", r"\bdemonstration"]},
    {"id": "amp", "label": "Method: adversarial motion priors", "stems": ["amp", "noamp", "styleoff"],
     "words": [r"\bamp\b", r"\bmotion prior", r"\bstyle reward\b"], "tracks": ["amp"]},
    {"id": "cpg", "label": "Method: CPG / parameter gait search", "stems": ["cpg"], "words": [r"\bcpg\b"],
     "tracks": ["cpg"]},
    {"id": "rl-only", "label": "Method: RL from scratch, no demonstrations (Goal 2)",
     "stems": ["rlonly", "walkscratch", "nobc", "crutchoff", "freshinit", "nocrutch", "scratch", "walkcurr"],
     "words": [r"\brl[_ -]only\b", r"\bfrom scratch\b", r"\bno demonstration", r"\bdemonstration-free\b", r"\bteacher-free\b"],
     "tracks": ["walkcurr", "nobc"]},
    {"id": "architecture", "label": "Method: network architecture / memory / dynamics models",
     "stems": ["gru", "hist", "arch", "tf", "transformer", "dynrep", "criticd", "mlp", "lstm", "recurrent", "singleframe",
               "obs", "cartfoot", "decleg"],
     "words": [r"\bgru\b", r"\blstm\b", r"\brecurrent\b", r"\btransformer\b", r"\barchitecture\b",
               r"\bobservation[- ]space\b", r"\baction[- ]space\b"],
     "tracks": ["arch", "dynrep"]},
    {"id": "exploration", "label": "Method: exploration, entropy, action noise schedules",
     "stems": ["sde", "gsde", "lowent", "explore", "entropy", "std", "logstd", "stdanneal", "exploreresettle",
               "klroll", "klrollback", "lowlr", "anneal"],
     "words": [r"\bexploration\b", r"\bentropy\b", r"\blog[_ -]?std\b", r"\bgsde\b", r"\blearning rate\b", r"\bkl[- ]guard\b"]},
    {"id": "curriculum", "label": "Method: curricula, easing, assistance fading",
     "stems": ["easy", "crossgrav", "halfgrav", "grav", "rung", "assist", "assistfade", "curriculum", "fade", "medhead",
               "sched", "residualfade", "residualgate", "gracefix"],
     "words": [r"\bcurriculum\b", r"\bgravity[- ]eas", r"\bassist(?:ance)?\b", r"\bfad(?:e|ing)\b", r"\brung\b"],
     "tracks": ["assistfade"]},
    {"id": "reward", "label": "Method: reward shaping and pricing",
     "stems": ["reprice", "charge", "duty", "legdutyratio", "swinggap", "plusduty", "freeprog", "fprent", "footprint",
               "penalty", "price", "loadeven", "headroom", "curhot", "rent"],
     "words": [r"\breward (?:term|shaping|pricing|stack)\b", r"\brepric", r"\bpricing\b", r"\bcharge\b", r"\bpenalt"]},
    # -------- lab-side (real-robot activity; not applied to RL runs)
    {"id": "sysid", "label": "System identification on the real robot", "lab_only": True,
     "stems": ["sysid", "bode", "hysteresis", "droop", "shear", "kneeloop", "servo", "spread", "swing", "backlash",
               "friction", "deadband", "latency", "radial"],
     "words": [r"\bsysid\b", r"\bbode\b", r"\bhysteresis\b", r"\bdroop\b", r"\bbacklash\b", r"\bdeadband\b",
               r"\bsystem id", r"\bservo (?:profile|model|current)\b", r"\bknee[- ]loop\b", r"\bradial\b", r"\bshear\b"]},
    {"id": "instrumentation", "label": "Cameras, tags, IMU, recording, loop-rate checks", "lab_only": True,
     "stems": ["camera", "recording", "record", "loop", "imu", "tag", "calibrate", "overrun", "video", "verification",
               "vision", "snapshot", "telemetry", "cameras"],
     "words": [r"\bcamera", r"\brecording\b", r"\bloop[- ]rate\b", r"\bimu\b", r"\bapriltag|\btags?\b", r"\bcalibrat",
               r"\boverrun", r"\bvideo\b", r"\bverif(?:y|ication)\b", r"\btelemetry\b", r"\bmotion recorder\b"]},
    {"id": "endurance", "label": "Endurance / long runs on the robot", "lab_only": True,
     "stems": ["endurance", "long", "patrol", "walklong", "gaitlong"],
     "words": [r"\bendurance\b", r"\bback and forth\b", r"\bpatrol\b", r"\b\d+ min\b"]},
    {"id": "scripted-gait", "label": "Scripted / programmed gaits (non-learned)", "lab_only": True,
     "stems": ["scripted", "noslip", "programmed", "shaking", "dance"],
     "words": [r"\bscripted\b", r"\bprogrammed\b", r"\bgaits? (?:\[?\d|1|9)\b", r"\bnoslip\b", r"\bopen-loop\b", r"\bdance\b"]},
]
TOPIC_BY_ID = {t["id"]: t for t in TOPICS}
POLICY_FILE_RE = re.compile(r"\b([A-Za-z0-9][\w.\-]*?)\.json\b")


def _tokens(*names: str) -> set[str]:
    out = set()
    for n in names:
        for t in re.split(r"[-_/ .:]+", str(n or "").lower()):
            t = re.sub(r"\d+[a-z]?$", "", t) or t
            t = re.sub(r"^\d+", "", t)
            if len(t) >= 2:
                out.add(t)
    return out


def classify(names: list[str], prose: str, cfg: dict | None = None, track: str | None = None,
             lab: bool = False) -> list[str]:
    """Topic ids for one item. Names are tokenised (a compound token matches a
    stem of >= 4 chars by substring, shorter stems exactly), prose is matched
    by word regex, cfg entries match `key` (presence) or `key=value`, the
    track matches exactly. Sub-topics (rise/hold/lower) imply their parent;
    lab_only topics are never applied to RL runs."""
    cfg = cfg or {}
    toks = _tokens(*names)
    text = " " + re.sub(r"\s+", " ", str(prose or "").lower()) + " "
    hits = []
    for t in TOPICS:
        if t.get("lab_only") and not lab:
            continue
        cfg_hit = False
        for c in t.get("cfg", ()):
            k, _, v = c.partition("=")
            if k in cfg and (not v or str(cfg[k]) == v):
                cfg_hit = True
                break
        hit = (track and track in t.get("tracks", ())) or cfg_hit \
            or any(stem == tok or (len(stem) >= 4 and stem in tok) for stem in t["stems"] for tok in toks) \
            or any(re.search(w, text) for w in t["words"])
        if hit:
            hits.append(t["id"])
    for t in list(hits):
        parent = TOPIC_BY_ID[t].get("parent")
        if parent and parent not in hits:
            hits.append(parent)
    return [t["id"] for t in TOPICS if t["id"] in hits]


# ------------------------------------------------------------ RL side
def tag_runs(runs: dict, entries: list[dict]) -> dict[str, list[str]]:
    current = rl_index.current_entries(entries)
    out = {}
    for run, r in runs.items():
        e = current.get(run, {})
        cfg, flags = rl_index.parse_args_list(e.get("extra_args"))
        # only the hypothesis's opening sentence: gate/verdict essays mention every skill
        prose = rl_index.first_sentence(e.get("hypothesis"), 300)
        out[run] = classify([run], prose, cfg, r.get("track"))
    return out


def lineages(runs: dict) -> dict[str, list[str]]:
    """root run -> every run in its tree (root first, then by created)."""
    by_root = defaultdict(list)
    for r in runs.values():
        by_root[r["root"]].append(r["run"])
    for root, members in by_root.items():
        members.sort(key=lambda x: (x != root, runs[x].get("created") or ""))
    return dict(by_root)


# ------------------------------------------------------------ Lab side
def load_lab_experiments(db: Path | None = None) -> list[dict]:
    """Robot Lab registry: one item per plan with its runs and learnings."""
    db = LAB2_DB if db is None else db
    if not db.is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        con.row_factory = sqlite3.Row
        plans = con.execute("select * from plans order by created_at").fetchall()
        runs = con.execute("select id, plan_id, started_at, finished_at, status, run_dir, summary_json "
                           "from runs order by started_at").fetchall()
        learn = con.execute("select run_id, created_at, text from learnings order by created_at").fetchall()
        con.close()
    except sqlite3.Error:
        return []
    by_plan = defaultdict(list)
    for r in runs:
        by_plan[r["plan_id"]].append(dict(r))
    by_run = defaultdict(list)
    for l in learn:
        by_run[l["run_id"]].append(l["text"])
    items = []
    for p in plans:
        prs = by_plan.get(p["id"], [])
        texts = [t for r in prs for t in by_run.get(r["id"], [])]
        blob = " ".join([p["title"] or "", p["why"] or "", p["protocol"] or "", p["status_note"] or ""] + texts)
        policies = sorted({m.group(1) + ".json" for m in POLICY_FILE_RE.finditer(blob)
                           if not m.group(1).endswith(("session", "summary", "events"))})
        found = ""
        for t in texts:
            t = re.sub(r"^\[\w+\]\s*", "", t.strip())
            if t and not t.startswith("{") and t not in ("see log", "see events/log"):
                found = t
                break
        items.append({
            "id": p["id"], "created": p["created_at"], "robot": p["robot"], "intent": p["intent"],
            "kind": p["kind"], "status": p["status"], "title": p["title"], "why": p["why"],
            "protocol": p["protocol"], "note": rl_index.first_sentence(p["status_note"], 200) or None,
            "found": rl_index.first_sentence(found, 240) or None,
            "runs": [{"id": r["id"], "status": r["status"], "started": r["started_at"], "dir": r["run_dir"]} for r in prs],
            "policies": policies,
            "topics": classify([p["title"] or "", p["protocol"] or "", *policies],
                               " ".join([p["title"] or "", p["why"] or "", p["protocol"] or ""]), lab=True),
        })
    return items


# ------------------------------------------------------------ gaits
def _policy_stem_candidates(name: str) -> list[str]:
    base = name[:-5] if name.endswith(".json") else name
    cands = [base]
    if "__" in base:                       # variant suffix, e.g. walk50hz_gru_dr10_envwide_s0__ws2000a80
        cands.append(base.split("__")[0])
    return cands


def gait_families(runs: dict, pols: dict, real: dict, lab: list[dict], lineage: dict) -> list[dict]:
    """One row per gait/policy file: its training run + lineage, its exports,
    and every real-robot trial that names it."""
    by_stem = {rl_index._stem(r): r for r in runs}
    names = set(pols) | set(real)
    for x in lab:
        names |= set(x["policies"])
    rows = []
    for name in sorted(names):
        p = pols.get(name, {})
        run = p.get("run")
        if not run:
            for c in _policy_stem_candidates(name):
                run = by_stem.get(rl_index._stem(c)) or by_stem.get(rl_index._stem("cw_" + c))
                if run:
                    break
        if not run and name not in pols and name not in real:
            continue          # a .json the lab named that is not a policy (layouts, incident reports, ...)
        root = runs[run]["root"] if run in runs else None
        members = lineage.get(root, []) if root else []
        trials = [x for x in lab if name in x["policies"]]
        agg = real.get(name)
        rows.append({
            "policy": name, "run": run, "track": runs[run]["track"] if run in runs else p.get("track"),
            "outcome": runs[run]["outcome"] if run in runs else None,
            "root": root, "lineage_runs": len(members),
            "lineage_outcomes": dict(Counter(runs[m]["outcome"] for m in members)) if members else {},
            "on_robots": p.get("on_robots") or [], "manifests": [m.get("candidate") or m.get("path") for m in p.get("manifests") or []],
            "lab_trials": len(trials), "lab_first": trials[0]["created"][:10] if trials else None,
            "lab_last": trials[-1]["created"][:10] if trials else None,
            "lab_robots": sorted({x["robot"] for x in trials}),
            "real": agg,
        })
    rows.sort(key=lambda r: (-(r["lab_trials"] + ((r["real"] or {}).get("legs", 0))), r["policy"]))
    return rows


# ------------------------------------------------------------ pages
def _run_line(r: dict) -> str:
    return (f"- {(r.get('created') or '')[:10]} **{r['outcome']}** `{r['run']}` [{r['track']}/{r.get('phase') or '?'}]"
            f"{' hw' if r.get('hardware_ready') else ''}: {rl_index.first_sentence(r.get('hypothesis'), 140)}")


def _lab_line(x: dict) -> str:
    extra = x["found"] or x["note"] or ""
    pol = f" ({', '.join(x['policies'])})" if x["policies"] else ""
    return f"- {x['created'][:10]} {x['robot']} **{x['status']}** {x['title']}{pol}" + (f" — {extra}" if extra else "")


def topic_page(tid: str, runs: dict, run_topics: dict, lab: list[dict], lineage: dict) -> str:
    t = TOPIC_BY_ID[tid]
    members = [runs[r] for r, ts in run_topics.items() if tid in ts]
    members.sort(key=lambda r: r.get("created") or "", reverse=True)
    labs = [x for x in lab if tid in x["topics"]]
    labs.sort(key=lambda x: x["created"], reverse=True)
    oc = Counter(r["outcome"] for r in members)
    o = [f"# {t['label']}", ""]
    if t.get("what"):
        o.append(t["what"] + "\n")
    o.append(f"{len(members)} RL runs ({', '.join(f'{k} {v}' for k, v in oc.most_common())}) · "
             f"{len(labs)} Robot Lab experiments. Rules: stems {t['stems']}, cfg {t.get('cfg', [])}, "
             f"tracks {t.get('tracks', [])}.\n")
    # approaches = lineages touching the topic
    roots = defaultdict(list)
    for r in members:
        roots[r["root"]].append(r)
    o += ["## Approaches tried (one lineage = one approach; biggest first)", "",
          "| lineage root | runs | outcomes | first .. last | tracks | what the root tried |", "|---|---|---|---|---|---|"]
    for root, rs in sorted(roots.items(), key=lambda kv: -len(kv[1]))[:60]:
        c = Counter(r["outcome"] for r in rs)
        dates = sorted(r.get("created") or "" for r in rs)
        hyp = rl_index.first_sentence(runs[root]["hypothesis"] if root in runs else "", 160) or "-"
        o.append(f"| `{root}` | {len(rs)} | {', '.join(f'{k} {v}' for k, v in c.most_common(4))} | "
                 f"{dates[0][:10]} .. {dates[-1][:10]} | {', '.join(sorted({r['track'] for r in rs}))} | {hyp} |")
    if len(roots) > 60:
        o.append(f"| … {len(roots) - 60} more lineages | | | | | |")
    o += ["", f"## Robot Lab experiments ({len(labs)}, newest first)", ""]
    o += [_lab_line(x) for x in labs] or ["- none tagged"]
    o += ["", f"## RL runs ({len(members)}, newest first)", ""]
    o += [_run_line(r) for r in members] or ["- none tagged"]
    return "\n".join(o) + "\n"


def gaits_page(fams: list[dict]) -> str:
    o = ["# Gaits / policy files — training lineage and real-robot trials", "",
         "One row per policy file that was exported, sits on a robot, or was named by a Robot Lab experiment. "
         "`lineage runs` = every RL run in the same family tree as the policy's training run "
         "(`ops.sh index lineage <run>` prints the tree; `ops.sh index gait <policy>` this row in full).", "",
         "| policy | training run (outcome) | track | lineage runs | lineage outcomes | on robots | lab trials | "
         "drive legs / speed_ratio / tilt | sweep roll rms |", "|---|---|---|---|---|---|---|---|---|"]
    for f in fams:
        rw = f["real"] or {}
        legs = (f"{rw.get('legs', 0)} / {rl_index._fmt_ratio(rw.get('speed_ratio_med'))} / "
                f"{rw.get('tilt_max_deg_med') if rw.get('tilt_max_deg_med') is not None else '-'}") if rw else "-"
        lo = ", ".join(f"{k} {v}" for k, v in sorted(f["lineage_outcomes"].items(), key=lambda kv: -kv[1])[:4]) or "-"
        o.append(f"| {f['policy']} | {f['run'] or '?'} ({f['outcome'] or '?'}) | {f['track'] or '?'} | {f['lineage_runs']} | {lo} | "
                 f"{', '.join(f['on_robots']) or '-'} | {f['lab_trials']}"
                 f"{' (' + (f['lab_first'] or '') + '..' + (f['lab_last'] or '') + ')' if f['lab_trials'] else ''} | {legs} | "
                 f"{rw.get('roll_rms_deg_med') if rw and rw.get('roll_rms_deg_med') is not None else '-'} |")
    return "\n".join(o) + "\n"


def gait_page(key: str, fams: list[dict], runs: dict, lab: list[dict], lineage: dict) -> str:
    f = next((x for x in fams if x["policy"] == key or x["run"] == key or key in x["policy"]), None)
    if f is None:
        return f"no gait/policy matching {key!r}"
    o = [f"# {f['policy']}", "", f"- training run: {f['run']} ({f['outcome']}), track {f['track']}, lineage root {f['root']}",
         f"- on robots: {', '.join(f['on_robots']) or '-'}; manifests: {', '.join(m for m in f['manifests'] if m) or '-'}"]
    if f["real"]:
        o.append(rl_index._real_line(f["policy"], f["real"]))
    trials = [x for x in lab if f["policy"] in x["policies"]]
    o += ["", f"## Robot Lab experiments naming it ({len(trials)})", ""]
    o += [_lab_line(x) for x in sorted(trials, key=lambda x: x["created"], reverse=True)] or ["- none"]
    members = lineage.get(f["root"], []) if f["root"] else []
    o += ["", f"## Training lineage ({len(members)} runs, root first)", ""]
    o += [_run_line(runs[m]) for m in members] or ["- (training run not in the ledger)"]
    return "\n".join(o) + "\n"


def index_page(run_topics: dict, lab: list[dict], runs: dict, fams: list[dict]) -> str:
    o = ["# Topics — every RL run and Robot Lab experiment by skill, method and gait", "",
         f"{len(runs)} RL runs and {len(lab)} Robot Lab experiments tagged by the explicit keyword rules in "
         "orchestrator/rl_topics.py (an item can carry several tags; untagged items are listed at the end). "
         "Each topic page lists the approaches (lineages), the lab experiments and every run. "
         "gaits.md joins policy files to their training lineage and real trials.", "",
         "| topic | RL runs | PASS/PARTIAL | FAIL | canary | Robot Lab experiments | page |", "|---|---|---|---|---|---|---|"]
    for t in TOPICS:
        tid = t["id"]
        rs = [runs[r] for r, ts in run_topics.items() if tid in ts]
        c = Counter(r["outcome"] for r in rs)
        nl = sum(1 for x in lab if tid in x["topics"])
        indent = "&nbsp;&nbsp;↳ " if t.get("parent") else ""
        o.append(f"| {indent}{t['label']} | {len(rs)} | {c.get('PASS', 0) + c.get('PARTIAL', 0)} | {c.get('FAIL', 0)} | "
                 f"{c.get('CANARY_PASS', 0)}/{c.get('CANARY_FAIL', 0)} | {nl} | {tid}.md |")
    untagged_r = [r for r, ts in run_topics.items() if not ts]
    untagged_l = [x for x in lab if not x["topics"]]
    o += ["", f"Gaits / policy files: {len(fams)} rows in gaits.md.", "",
          f"Untagged: {len(untagged_r)} RL runs, {len(untagged_l)} lab experiments" +
          (" — " + ", ".join(f"`{r}`" for r in sorted(untagged_r)[:20]) if untagged_r else "") +
          (" — lab: " + "; ".join(x["title"][:60] for x in untagged_l[:10]) if untagged_l else "") + ".", ""]
    return "\n".join(o)


# ------------------------------------------------------------ build / queries
def compute(runs: dict, entries: list[dict], pols: dict, real: dict, lab: list[dict] | None = None) -> dict:
    lab = load_lab_experiments() if lab is None else lab
    run_topics = tag_runs(runs, entries)
    lineage = lineages(runs)
    fams = gait_families(runs, pols, real, lab, lineage)
    return {"run_topics": run_topics, "lineage": lineage, "lab": lab, "gaits": fams}


def build(out: Path, runs: dict, entries: list[dict], pols: dict, real: dict) -> dict:
    d = compute(runs, entries, pols, real)
    tdir = out / "topics"
    tdir.mkdir(parents=True, exist_ok=True)
    for t in TOPICS:
        (tdir / f"{t['id']}.md").write_text(topic_page(t["id"], runs, d["run_topics"], d["lab"], d["lineage"]))
    (tdir / "gaits.md").write_text(gaits_page(d["gaits"]))
    (tdir / "INDEX.md").write_text(index_page(d["run_topics"], d["lab"], runs, d["gaits"]))
    (out / "topics.json").write_text(json.dumps({
        "topics": [{k: v for k, v in t.items() if k in ("id", "label", "parent", "what")} for t in TOPICS],
        "run_topics": d["run_topics"],
        "lab_experiments": d["lab"],
        "gaits": d["gaits"],
    }, indent=1, default=str) + "\n")
    return {"topics": len(TOPICS), "lab_experiments": len(d["lab"]), "gaits": len(d["gaits"]),
            "untagged_runs": sum(1 for ts in d["run_topics"].values() if not ts)}
