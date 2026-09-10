# STATUS — two walking goals, each in sim and on hardware

Goal structure clarified by Lukas on 2026-09-08. This is an operator-facing
digest, not a live fleet snapshot. `RL_GOALS.md` owns purpose and priorities;
`CURRENT_TRUTHS.md` owns accepted evidence. Consult the state ledger and
track journals for current run/queue status.

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
**`rl_only` result:** genuine interactive PASS on its champion below —
`stalled_phases: []`, 0 falls, 0 rejected commands, real direction-correct
translation every phase (`CURRENT_TRUTHS.md` 09-10 root-cause entry).
**`any_means` result:** SUBSTANTIALLY IMPROVED, not yet a clean PASS —
root cause found (09-10, later cycle): the interactive session's
velocity-command ramp used a fixed RATE instead of training's fixed-
DURATION blend, producing a genuine coincidental full-stop for the
diag-left->reverse command pair; fixed (`_PlayTraj`,
`rl_move/sim/play_core.py`). Reverse-phase locomotion fraction improves
from a consistent 0.19-0.21 (pre-fix, FAIL, 2/2 runs) to 0.246/0.313/
0.333/0.273 across 4 post-fix repeats (mean 0.291, 3/4 clean PASS, one
still fractionally under the 0.25 stall floor) — do not call this fully
closed; a residual short-window gait-reversal transient and/or HTTP
timing jitter may explain the remaining borderline run. Full derivation:
`CURRENT_TRUTHS.md` 09-10, top of file.
Physical acceptance needs a named build/controller, a bounded joystick
trial with video/telemetry, and reported direction/speed/yaw/start/stop
limits; `rl_only` also needs clean training ancestry. Next: a larger
held-out repeat count (n>=8-12) or a phase-window review to settle the
residual `any_means` borderline case, then the best-supported
candidate's measured physical comparison through Robot Lab; neither
waits for every method.

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
front leg's swing (8 repair mechanisms CLOSED FAIL, `walkcurr/STATUS.md`
09-09); joystick DONE-gate FAILS on slip (>3x band) — neither blocks the
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
