# STATUS — two walking goals, each in sim and on hardware

Goal structure clarified by Lukas on 2026-09-08. This is an operator-facing
digest, not a live fleet snapshot. `RL_GOALS.md` owns purpose and priorities;
`CURRENT_TRUTHS.md` owns accepted evidence. Consult the state ledger and
track journals for current run/queue status.

**UPDATE 09-10 (op_20260910_50hz):** deployment control rate is now
**50 Hz** — hexapod2's MCU bridge (18-servo read 9-13 ms + write
~4.4 ms) trips the timing fault at 100 Hz within 3-52 ticks, while
25 Hz ran 150 ticks clean; the 08-24 100 Hz order is superseded for
robot-bound candidates (CURRENT_TRUTHS top entry). A 5-arm 50 Hz
retrain fill (walk x2, turn x2, stand/sit x1) launched 09-10; every
PASS exports v2-stamped `--training-hz 50` artifacts into
`linux_control/policies/*50hz*` toward a 50 Hz todaypolicy bundle
(stand/lower + walk + turn). See standwalk/amp/todaypolicy STATUS.

## Parent outcomes

1. **`any_means`: smooth joystick walking in sim and physically by any effective means.**
   Scripted, searched, demonstration-assisted or learned controllers all
   count. Methods: `joystick`, `amp`, `cpg`, `standwalk`, `assistfade`, `todaypolicy`.
2. **`rl_only`: the same outcome, learned entirely through RL with no
   demonstrations anywhere in the walking policy's training lineage.**
   Method: `walkcurr`. BC/AMP/scripted-gait assistance belongs to
   `any_means`, even if assistance later ends.

Both proceed in parallel. Each needs an interactive joystick sim demo and
viewable video as well as physical walking evidence. Report readiness, demo
link/launch command and remaining limits separately for each deliverable.
Non-interactive reproducible sim video exists for a candidate under each
goal (below). **UPDATE 09-10:** the browser's own HTTP joystick API
(`/api/rl/...`) is headlessly drivable from a cloud pod with no display
(`web_session_drivecapture.py`) — the earlier "needs a display,
irreducible-to-cloud" read was wrong about that specific claim. Chasing
it found and fixed two real config-threading bugs (silently-clobbered
`joint_action_box`/`bias` and `walk_obs_body_vel` explicit overrides) and
one real tool bug (missing joystick heartbeat resend, now fixed).
**`rl_only` result:** interactive PASS on its champion below — 0 falls,
0 rejected commands, strong direction-correct translation on
forward/crab-right/diag-left/restart, but the **reverse phase is a
genuine, confirmed defect**: it nets only ~0.15-0.06 of commanded speed
in the commanded direction (two independent metrics agree closely),
despite real motion (magnitude ~0.5-1.0) — consistent with (not a new
instance of) the already fully-closed `walkcurr` 180-degree-heading
front-pair leg-sacrifice mechanism. **`any_means` result:** interactive
PASS with 0 falls/rejections on every phase incl. reverse; a
`web_session_drivecapture.py` timebase bug (this tool's phases were
scheduled on wall-clock while the server it drives over HTTP was
quietly stepping physics at ~0.26-0.87x real time, model-source
dependent) had made "reverse" look like a standout-soft, ~25%-
intermittent residual through most of 09-10's investigation — fixed
(phase transitions now gate on the server's own simulated clock), and
the properly-measured picture is a smaller, general (not reverse-
specific) softness on commands with no forward-velocity component
(crab-right now the weakest, reverse mid-pack). **Full derivation,
per-phase tables, and which earlier same-day numbers this supersedes:**
`CURRENT_TRUTHS.md` 2026-09-10, top entry ("ROOT CAUSE + FIX"). Physical
acceptance needs a named build/controller, a bounded joystick trial
with video/telemetry, and reported direction/speed/yaw/start/stop
limits; `rl_only` also needs clean training ancestry.

## Recorded sim-demo candidates and limitations

**`any_means`: `todaypolicy-mlpsf-tuck-v1`**, PACKAGED 08-30, all TODAY bars
passing on a fresh controller-side full-mesh regen: scripted-or-learned tuck
stand/lower plus `cw-walk-allheading-mlp-singleframe-acq1-stdanneal`. 0
terminations, no sacrificed legs, course error median 2.42°/p90 6.98°,
progress ratio 0.418 — GO for controller handoff, not physical acceptance;
speed-soft, zero turn authority. Evidence: `todaypolicy/bundle_mlpsf_
tuck_v1/`. The 09-05 delivery verification flagged a model/regen mismatch —
resolve from `todaypolicy/hardware_delivery/STATUS.md` before transfer.
Interactive HTTP capture (09-10): real checkpoint, 0 falls, 0 rejected
commands; the "reverse" stall found earlier the same day is root-caused
and mostly fixed (later 09-10 cycle, `_PlayTraj` command-blend fix) —
reverse-phase locomotion fraction now 0.246/0.313/0.333/0.273 across 4
repeats (3/4 clean PASS) vs. 0.19-0.21 pre-fix; still not a clean
unanimous PASS, see `CURRENT_TRUTHS.md`.

**`rl_only`: `ppo_goal_cw_walkscratch_crutchoff_s0_widen8_legdutyratio_
swinggap_dose10_plusduty_acq1_cont10m.zip`** (walkcurr, no BC/AMP/demo in
lineage), recipe-default widen8 champion, durability-confirmed at 50M steps.
Reproducible non-interactive video (09-09, `ops.sh drivevideo ... --script
human[_turn]`): forward/crab-right/diag-left/reverse/**stop**/**restart**,
0 falls, `gait_valid=true`, `sacrificed_legs=[]` for the full 26 s episode.
Interactive launch: `sim_viewer/sim_web.sh --walk rl_move/sim/policies/<name
above>`; headless HTTP capture (09-10, `web_session_drivecapture.py`, fixed
same day to resend the drive heartbeat like the real browser does) now
PASSES with real translation: `stalled_phases: []`, 0 falls, 0 rejected
commands, per-phase `vx_body`/`vy_body` direction-correct and nonzero
through forward/crab-right/diag-left/reverse/restart
(`logs/manual_drive/rlonly_champion_websession_capture_09-10_heartbeatfix/`,
`CURRENT_TRUTHS.md` 09-10 root-cause entry). Known
limits: a SUSTAINED (~15s) off-forward heading chronically sacrifices one
front leg's swing (12 repair mechanisms CLOSED FAIL incl. the entire named
RND family — full-obs/heading-gated/per-leg-obs-masked — `walkcurr/
STATUS.md` 09-10; no named lever remains, needs a fresh design note);
joystick DONE-gate FAILS on slip (>3x band) — neither blocks the
non-interactive deliverable above. Physical-handoff prep (09-09): exported
to the robot's numpy runtime (N-layer/ELU support) with a transfer manifest
+ registered bounded-trial plan at `walkcurr/bundle_rlonly_v1/` (walk only).

## Recorded method milestones — not parent-goal completion

- `joystick`: GREEN 08-23 at the legacy 60 s randomized MuJoCo gate
  (`stotight45-seed13`, zero falls); physical drive goes through Robot Lab.
- `amp`: GREEN 08-23 at sim-transfer M5 (`phasehz11_s29`, demonstration-
  assisted); hardware M6 goes through Robot Lab under Goal 1.
- `cpg`: GREEN 08-23 at the contextual walk/turn/stop gate (adoption candidate).
- `walkcurr`: sim-demo candidate above (09-09); easy-sim acquisition is an
  intermediate Goal-2 milestone (journal/`CURRENT_TRUTHS.md`).
- `standwalk`: single-policy method stays separate from controller
  composition — check its journal before proposing a new lever.
- `assistfade`: rungs 1-4 + residual-anneal-gate (~36 arms) now ALL closed —
  every "fade assist to full raw authority" mechanism fails on mesh/100Hz.
  Persistent BC-anchor rung 0 stays production-usable; assisted ancestry
  cannot qualify for Goal 2.
- `todaypolicy`: the 08-30 bundle packaging is a milestone; `env_yawpri`
  gained yaw at a 55% cost, shared/fixed-duty variants refuted (delivery journal).

Registry: `rl_move/orchestrator/tracks.json`. Method evidence and queues:
`rl_docs/tracks/<track>/STATUS.md`. No closed recipe is reopened by this
reorganization; there is no requirement to make every method green.

## Ownership and actual waits

Cloud cycles prepare sim evidence and controller handoffs; Robot Lab owns
serialized physical experiments under standing authority and live camera/
telemetry/abort rules. Routine calibration/bounded motion/deployment are
not blanket operator blockers; only hands-on needs or spend/capacity
increases beyond guardrails are operator waits.

## Doc rules

Keep under 100 lines. Replace stale status; put history in `RL_LOG.md` and
generated run docs. Do not infer current fleet activity from this digest.
