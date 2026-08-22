# STATUS - campaign dashboard

<<<<<<< Updated upstream
Last updated: 2026-08-21 (two-track reset, incl. the 08-22 plant-gate
and bank-repair findings). Operator-facing dashboard, not a history
file. `CURRENT_TRUTHS.md` wins on conflict. Run-level evidence lives
in `rl_docs/runs/`, `RL_LOG.md`, and W&B.

## Current ruling

The operator reset the campaign to exactly two goals (08-21):

1. `joystick` — RL from the scripted gait to joystick control.
   Gate: 60 s randomized joystick script in MuJoCo, zero falls,
   directions followed, slip/m <=~2.9 (teacher band).
2. `amp` — from-scratch AMP program (`rl_docs/AMP_LOCOMOTION.md`,
   no Isaac Lab). Gate: milestone M5, MuJoCo cross-engine transfer.

The loop works until both gates are green: no operator pauses, tools
get built in-cycle, and bad evals with rising reward mean
continue-and/or-realign, never a reflex fail. Out-of-scope runs are
operator-kick only.

## WAITING-ON

- [operator, bench-parked] Everything physical: bench promotion,
  calibration readings still on the robot, any hardware test. Parked
  until the robot is back; does not block either track.
=======
Last updated: 2026-08-22 ~04:4x UTC. Operator-facing dashboard, not a history file.
`CURRENT_TRUTHS.md` wins on conflict; run evidence in `rl_docs/runs/`, W&B.

## WAITING-ON

- Fast-gait fork RESOLVED by operator order fb_20260822T032514
  (08-22 ~03:2x: "make the reward correctly aligned and rerun"):
  staged phase-RL rung A `cw-dep-bcgait4-phasedir2-staged-fwd` is
  QUEUED (forward-only, fixed 0.08, aligned pricing: stride-averaged
  course + EMA overspeed band + clone-banded loadslip gate/excess +
  travel floor; phase-locked raw-dialect BC anchor). Preflight bank
  `tests/test_phasedir_semantics.py` 20/20 GREEN at 1f0eadbd: clone
  behavior out-earns every measured phasedir1 attractor per heading
  bin incl. rear. Gate is CLONE-RELATIVE per bin; rungs B (heading
  set) / C (full headings) / D (irregular changes) pre-registered in
  the run gate, each launched only on the prior rung's PASS. One
  deviation filed: q_20260822T0430Z (stall>park bank tail inverted by
  the ordered slip pricing; obey buries both, margins >=100).
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
  Walk fix arm `cw-dep-bcgait1-plant150-1` LAUNCHED 08-22 (banks
  repaired); stance arm `cw-stand-footlow2-plant150-1` still blocked
  by the 7-FAIL rise residue below. Operator decides later: promote
  successors / keep old-plant answer for bench. Remaining calibration
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
- [operator] Recover mode: flip handling (ship with flip unsupported
  vs order a flip-hardening arm from s13; champion packaged +
  runner-gate-verified). [operator, bench-parked] recover hardware
  items: 185 deg tilt envelope, on-robot transformer compute check,
  level-IMU bias calibration (`rl_docs/RECOVER_DEPLOY.md` 2/4/5).
- Agent-doable queue (08-22 ~04:4x): topmost = the [code] rise-bank
  residue above (unblocks the stance fix arm); then rung-A triage when
  it finishes. Post-lower contract + bench promotion remain [operator].
>>>>>>> Stashed changes

Nothing else. All design/code/gate questions are agent-doable under
the 08-21 assume-and-go ruling.

## Live work

- IN FLIGHT: `cw-dep-bcgait1-plant150-1` — walk-champion re-hardening
  on the measured tibia-150 plant (the download hierarchy hard-fails
  the session gate there; matched 128 mm control passes). Triage
  normally on finish; serves the joystick track's baseline.
- Topmost agent-doable (joystick): the 7-test tibia-150 semantics-
  bank recalibration residue (rise-ref re-mint first — it unblocks
  the spec'd stance fix arm `cw-stand-footlow2-plant150-1`). The
  convention leak itself is repaired (`sim_gait_compat.py`).
- Then per `RL_PLAN.md`: the 60 s joystick gate harness + aligned
  reward bank; re-run the phase-RL question on the repaired sim (the
  phasedir1 verdict is env-confounded); fine-tune from the
  phase-conditioned BC clone.
- amp: M0 infrastructure on the MJX stack (joystick-command env,
  actor/critic split, GRU actor, motion library, discriminator),
  then M0/M1 smoke checks, then Wave 1.

## Track snapshot

- `joystick`: created 08-21. Strong starting assets (teacher clean at
  measured plant; phase clone passes direction-first curriculum
  zero-RL). Bank recalibration, then the gate harness, are the first
  deliverables.
- `amp`: created 08-21. Charter adopted; nothing built; M0 next.

## Baseline

Fallback deployable answer remains the hierarchy in
`rl_docs/DOWNLOAD_ANSWER.md` (`footlow2_hard1` + `bcgait1_hard1` +
session controller; det 0.967 / sto 0.853, n=600) — but those are
OLD-PLANT numbers: at the measured tibia-150 plant it hard-fails the
session gate, and the plant-150 fix arms above exist to repair that.

## Doc rules

<<<<<<< Updated upstream
Keep this file under 100 lines. Replace stale status, do not append
history. One-line cycle history in `RL_LOG.md`; long audits in
`archive/`.
=======
Unchanged: the hierarchical session composition in `rl_docs/DOWNLOAD_ANSWER.md`:

- stance: `ppo_goal_cw_stand_footlow2_hard1`
- walk: `ppo_goal_cw_dep_bcgait1_hard1`
- session controller: per-mode re-anchor, entry slew on, STOP routes to stance hold, rot60 wrapper default-on

Bulk held-out session gate: det 0.967, sto 0.853 across n=600 fresh
sessions. Single-model distills remain worse. Known shipping gaps are
post-lower rise, takeoff roll transient, and unproven learned stand-up on
hardware.

## Live Work

- `cw-dep-bcgait1-plant150-1` (walk plant-150 fix arm, hw) — training.
- `cw-dep-bcgait4-phasedir2-staged-fwd` (staged phase-RL rung A,
  operator order fb_20260822T032514) — queued to drain.
- Stance plant-150 fix arm blocked on the rise-bank residue
  (WAITING-ON [code]). DOWNLOAD_ANSWER unchanged (plant caveat noted
  in it); nobc anti-slip sub-line stopped
  (`rl_docs/tracks/nobc/STATUS.md`).

## Current Findings

- Product baseline is still the stance/walk hierarchy above, BUT its
  gate evidence is old-plant: at tibia-150 it hard-fails the session
  gate (matched 128 mm control passes). Walk fix arm training; stance
  fix arm awaits the rise-bank residue.
- Fast gait, compressed (detail: CURRENT_TRUTHS + `rl_docs/tracks/hw/STATUS.md`): raised profile kills warm-started policies; fresh BC-INIT clone survives it; five RL levers refuted (cadence, tracking price, speed-obs+charges, +steps, full-heading phase RL — the last env-confounded by the 30660b51 sim corruption); the ZERO-RL phase clone passes the whole direction-first curriculum. NOW: operator-ordered staged phase RL with aligned reward is running (rung A queued 08-22, clone-relative gate).
- Post-lower rise remains the main stance/session contract decision: `postlower4` looks better only under remaining-rise semantics; promotion requires an operator contract call.
- Recover/tangle: reopened 08-20, sim/deploy-ready: champion `predictive1b-pop3-s13` packaged, runner contract test-locked, ladder through the runner matches the training-path gate (DR-0 21/23, own-DR 22/23; flip out of envelope 0/6). Additional mode only; rise+walk answer unchanged. Details: `rl_docs/RECOVER_DEPLOY.md`.
- Coxa geometry sweep says coxa length is a yaw-margin/scrub lever, not a walking-speed lever; no sim pivot follows from it.

## Operator Gates

Open decisions that should not be resolved by autonomous doc rereads:

- Post-lower contract: accept remaining-rise semantics generally, and decide whether to promote `postlower4` over `footlow2_hard1`.
- Fast gait: order fb_20260822T032514 executing — staged phase-RL
  ladder running under the aligned reward; next operator touchpoint is
  the rung-A clone-relative verdict.

- Measured plant: MEASURED 08-22 — the hierarchy hard-fails the session gate at tibia-150 (matched control at 128 mm passes). Fix arms spec'd, launch-blocked on the red banks ([code], agent-doable); the operator decision is PROMOTION of any passing successor vs keeping the old-plant answer for bench vs folding into the fast-gait fork.
- Hardware return: bench-promote the hierarchy or fall back to scripted stand/sit glides as appropriate.
- Recover mode: flip handling (ship unsupported vs flip-hardening arm); hardware-side recover items parked for the bench.
- Non-sprint tracks: arch/dynrep/quad/turn/nobc/multitask stay gated unless directly serving rise+walk download readiness or explicitly ordered.

## Track Snapshot

- `hw`: mainline — plant-150 walk fix arm + staged phase-RL rung A live;
  product baseline unchanged (old-plant evidence).
- `arch` / `dynrep` / `quad` / `turn` / `multitask`: secondary under SIM
  SPRINT; useful partials, no deployment change.
- `nobc`: from-scratch gait closed (exploration, not reward, is the
  blocker; sub-line stopped by operator instruction).

## Doc Rules

Keep this file under 150 lines. Replace stale status, do not append history.
Use `RL_LOG.md` for one-line cycle history and `rl_docs/runs/` for run
facts. Long audits belong in `archive/`.
>>>>>>> Stashed changes
