# STATUS - campaign dashboard

Last updated: 2026-08-22 UTC. Operator-facing dashboard, not a history file.
`CURRENT_TRUTHS.md` wins on conflict; run evidence in `rl_docs/runs/`, W&B.

## WAITING-ON

- [operator] Fast-gait fork (open; updated 08-22 ~01:3x UTC): five RL
  levers refuted (list: Current Findings / CURRENT_TRUTHS). Standing
  candidate is the ZERO-RL phase-conditioned BC clone
  (`ppo_goal_cw_bcgait_init_fullprof_phase1`): passes the entire
  direction-first curriculum at the measured plant, zero falls (SKILLS
  row). Per operator-keyed fb_20260822T003132, the phasedir1 FAIL is
  scoped to full-heading-from-rung-1 phase RL; the STAGED curriculum
  is untried and pre-registered in hw STATUS "Next" (operator
  permission required). Decision: adopt the zero-RL clone (then DR
  panel + board-side phase-clock CODE), staged-curriculum phase RL,
  new RL pricing, or park.
- [operator] MEASURED-PLANT GATE BREAK (new, 08-22 ~02:5x UTC;
  ASSUMPTION/assume-and-go, operator to review — measured inside a
  listed operator gate, see OPERATOR_QUESTIONS.md): the shipped
  download hierarchy (footlow2_hard1 + bcgait1_hard1, md5-verified)
  HARD-FAILS the interactive session gate on the measured tibia-150
  plant: FELL on sit (tilt_pitch) and reverse drive (tilt_roll),
  sit_descends FAIL, fwd yaw drift -21.8 deg. Matched control (same
  HEAD harness, only a4beb8af reverted -> 128 mm plant, same pod):
  PASS all hard gates. So the plant correction ALONE breaks the
  shipped answer; the n=600 bulk numbers in DOWNLOAD_ANSWER are
  old-plant facts. Evidence:
  `logs/ckpt_eval/plantgate_tibia150_session/` (+`control_oldplant/`).
  Fix arms `cw-stand-footlow2-plant150-1` / `cw-dep-bcgait1-plant150-1`
  are SPEC'D (hw STATUS "Next") but LAUNCH-BLOCKED by the red banks
  below. Operator decides later: promote successors / keep old-plant
  answer for bench / fold into fast-gait fork. Remaining calibration
  READINGS still live only on the unreachable robot
  (fb_20260821T224209) [bench-parked].
- [code] SEMANTICS BANK RESIDUE — 7 tibia-150 recalibration FAILs
  (updated 08-22, bank bisect/REPAIR LANDED): the 08-21/22 breakage
  was ROOT-CAUSED by bisect to 30660b51 ("measured stand geometry"),
  NOT the quad commits: it switched the scripted-gait/IK knee output
  to the robot's ABSOLUTE-tibia convention and the hardware default
  stand home to +19/+28 absolute, while the MuJoCo knee hinge (and
  every checkpoint) is femur-RELATIVE — every rl_move consumer of
  desired_deg/_leg_ik/standing_pose was silently mis-posed (full bank
  was 43 FAIL). FIXED at the boundary: `linux_control/
  sim_gait_compat.py` (sim-relative adapters; hardware untouched) +
  `_default_plant_deg` guard (near-singular +19/+9-rel default stand
  NOT adopted; captured plants convert). Bank now 7 FAIL, ALL
  reproduced at a4beb8af pre-convention => TRUE tibia-150 residue:
  rise_valid_plant, score_replay (stale 128 mm rise ref npz),
  rise_rock, trans_drag, getup_honest_ordering, recover_floor_rungs,
  fastprof_obeying. sim_env/mode_seq/bc_anchor/walk suites green.
  AGENT-DOABLE next: re-mint rise ref at tibia-150
  (extract_rise_ref) + recalibrate the 5 other tests per root cause;
  rise-family green unblocks the stance fix arm. NOTE: the walk-bank
  family is GREEN => walk fix arm launched (see hw STATUS).
  phasedir1 re-read UPGRADED: it trained on the corrupted sim
  (061dfe69 contains 30660b51 — walk spawns + BC anchor mis-posed);
  its RL-degradation verdict is env-confounded, candidate re-run on
  the repaired sim before any phase-RL conclusion. The 08-22
  plantgate 150-vs-128 DIFFERENTIAL stands (both arms shared the
  harness), but its ABSOLUTE numbers predate the repair.
- [operator] Recover mode flip handling (since 08-20 ~23:00 UTC): the
  recover champion is packaged + sim-gate-verified through the
  deployment runner (see below), but flip (full inversion) is out of
  envelope (0/6 own-DR isolation). Ship recover with flip unsupported,
  or order a flip-hardening arm from s13.
- [operator, bench-parked] Recover-mode hardware items: 185 deg tilt
  envelope inside recover mode only, on-robot transformer compute
  check (torch/ONNX at 25 Hz), level-IMU bias calibration. Parked
  until the robot is back (`rl_docs/RECOVER_DEPLOY.md` blockers 2/4/5).
- Agent-doable queue NON-EMPTY (08-22, updated after bank repair):
  topmost = [code] the 7-test tibia-150 recalibration residue above
  (rise-ref re-mint first: unblocks the stance fix arm), then
  [triage] phasedir1 re-read/re-run on the repaired sim. Walk fix
  arm `cw-dep-bcgait1-plant150-1` is QUEUED/training. Post-lower
  contract + bench promotion remain [operator].

## Read First

Default startup packet for an agent cycle:

1. `RL_GOALS.md`
2. `CURRENT_TRUTHS.md`
3. `RL_PLAN.md`
4. this file
5. `rl_docs/DOWNLOAD_ANSWER.md`
6. the relevant `rl_docs/tracks/<track>/STATUS.md`
7. `RESEARCH_RULES.md` and `RUN_INTERPRETATION_RULES.md` before launch or triage

Do not broad-sweep `archive/`, review bundles, `RL_LOG.md`, or generated
`rl_docs/runs/` unless answering a specific historical/run question.

Robot-control/web edit loop: `make robot-check / robot-unit-check /
robot-status / robot-deploy` (no robot motion; `make robot-resolve` for
flaky `hexapod.local`; details `linux_control/README.md`).

## Current Ruling

SIM SPRINT remains binding: the single deliverable is download-ready
rise + walk in MuJoCo. Bench-only actions parked; non-hw tracks launch
only if they directly serve the sprint or the operator orders them.

## Download Answer

Unchanged: the hierarchical session composition in `rl_docs/DOWNLOAD_ANSWER.md`:

- stance: `ppo_goal_cw_stand_footlow2_hard1`
- walk: `ppo_goal_cw_dep_bcgait1_hard1`
- session controller: per-mode re-anchor, entry slew on, STOP routes to stance hold, rot60 wrapper default-on

Bulk held-out session gate: det 0.967, sto 0.853 across n=600 fresh
sessions. Single-model distills remain worse. Known shipping gaps are
post-lower rise, takeoff roll transient, and unproven learned stand-up on
hardware.

## Live Work

Nothing training. Two plant-150 re-hardening fix arms are spec'd but
LAUNCH-BLOCKED on the red semantics banks (see WAITING-ON [code]
entry) — that bank repair is the topmost agent-doable item.
The whole 08-21/22 fast-gait chain is verdicted (see WAITING-ON +
Current Findings); the nobc anti-slip canary failed honestly and its
sub-line is stopped (`rl_docs/tracks/nobc/STATUS.md`).
DOWNLOAD_ANSWER unchanged (with the new plant caveat noted in it).

## Current Findings

- Product baseline is still the stance/walk hierarchy above, BUT its
  gate evidence is old-plant: at the measured tibia-150 plant it
  hard-fails the session gate (falls on sit + reverse; matched
  128 mm control passes). Fix arms await green semantics banks.
- Fast gait, full history compressed (details: CURRENT_TRUTHS + `rl_docs/tracks/hw/STATUS.md`): the raised servo profile destabilizes every WARM-STARTED/transplanted policy (4-way A/B: train-through + ramp-in x mid + full dose all FAIL identically); a fresh BC-INIT clone of the native-cadence teacher survives the full profile (`fastbc1` PASS but 2x overspeed); FIVE RL levers to make it obey are refuted (faster cadence at teacher level, k_walk_cmd_track, speed-obs+charges, +4M more steps, phase-obs+fixed-speed). NEW 08-22: the phase-conditioned BC clone with ZERO RL passes the whole direction-first curriculum (see WAITING-ON + SKILLS) — the standing fast-gait candidate is now imitation-only.
- Post-lower rise remains the main stance/session contract decision: `postlower4` looks better only under remaining-rise semantics; promotion requires an operator contract call.
- Recover/tangle: reopened 08-20, sim/deploy-ready: champion `predictive1b-pop3-s13` packaged, runner contract test-locked, ladder through the runner matches the training-path gate (DR-0 21/23, own-DR 22/23; flip out of envelope 0/6). Additional mode only; rise+walk answer unchanged. Details: `rl_docs/RECOVER_DEPLOY.md`.
- Coxa geometry sweep says coxa length is a yaw-margin/scrub lever, not a walking-speed lever; no sim pivot follows from it.

## Operator Gates

Open decisions that should not be resolved by autonomous doc rereads:

- Post-lower contract: accept remaining-rise semantics generally, and decide whether to promote `postlower4` over `footlow2_hard1`.
- Fast gait: OPEN — five RL levers refuted (see WAITING-ON, incl. the fb_20260822T003132 scoping: staged-curriculum phase RL is untried); choose: adopt the zero-RL phase clone (then DR panel + board phase-clock runner CODE), staged-curriculum phase RL, a new RL pricing, or park.
- Measured plant: MEASURED 08-22 — the hierarchy hard-fails the session gate at tibia-150 (matched control at 128 mm passes). Fix arms spec'd, launch-blocked on the red banks ([code], agent-doable); the operator decision is PROMOTION of any passing successor vs keeping the old-plant answer for bench vs folding into the fast-gait fork.
- Hardware return: bench-promote the hierarchy or fall back to scripted stand/sit glides as appropriate.
- Recover mode: flip handling (ship unsupported vs flip-hardening arm); hardware-side recover items parked for the bench.
- Non-sprint tracks: arch/dynrep/quad/turn/nobc/multitask stay gated unless directly serving rise+walk download readiness or explicitly ordered.

## Track Snapshot

- `hw`: mainline. Fast-gait fork operator-gated after five refuted RL levers; zero-RL phase clone is the standing candidate. Product baseline unchanged.
- `arch`: temporal/unified-controller research has useful partials but no deployment change.
- `dynrep`: causal-transformer/dynamics representation work found partial walking signals but no replacement for the baseline.
- `nobc`: from-scratch gait stays closed (08-21 anti-slip canary froze; blocker is exploration from a blank init; sub-line stopped).
- `quad`: specialist/party-trick line, not a current sprint deliverable.
- `turn`: rot60/mirror tooling is useful, but yaw/turn is not the current blocker.
- `multitask`: pause lifted 08-15, but secondary under SIM SPRINT.

## Doc Rules

Keep this file under 150 lines. Replace stale status, do not append history.
Use `RL_LOG.md` for one-line cycle history and `rl_docs/runs/` for run
facts. Long audits belong in `archive/`.
