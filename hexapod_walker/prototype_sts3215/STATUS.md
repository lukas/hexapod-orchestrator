# STATUS - campaign dashboard

Last updated: 2026-08-22 ~04:4x UTC. Operator-facing dashboard,
not a history file. `CURRENT_TRUTHS.md` wins on conflict. Run-level
evidence lives in `rl_docs/runs/`, `RL_LOG.md`, and W&B.

## Current ruling

The operator reset the campaign to exactly two goals:

1. `joystick` - RL from the scripted gait to joystick control.
   Gate: 60 s randomized joystick script in MuJoCo, zero falls,
   directions followed, slip/m within the teacher band.
2. `amp` - from-scratch AMP program (`rl_docs/AMP_LOCOMOTION.md`,
   no Isaac Lab). Gate: milestone M5, MuJoCo cross-engine transfer.

The loop works until both gates are green: no operator pauses, tools
get built in-cycle, and bad evals with rising reward mean continue
and/or realign, not reflex fail. Out-of-scope runs are operator-kick
only.

## WAITING-ON

- [code] Semantics bank residue: the 08-21/22 bank collapse was
  root-caused to 30660b51, which leaked the robot's absolute-tibia
  knee convention into MuJoCo's femur-relative hinge frame. Boundary
  repair landed in `linux_control/sim_gait_compat.py`; bank is down
  to 7 true tibia-150 recalibration failures. Next code item is
  re-minting the rise reference and recalibrating the remaining tests;
  that unblocks `cw-stand-footlow2-plant150-1`.
- [operator, bench-parked] Physical promotion and calibration readings:
  the measured-plant numbers still live on the robot, and hardware
  promotion waits until bench work resumes.
- [operator] Recover mode: decide whether to ship flip unsupported or
  order flip-hardening. Hardware-side recover checks are parked.

## Live work

- `cw-dep-bcgait1-plant150-1` - walk champion re-hardening on the
  measured tibia-150 plant. Launched after the convention-bank repair.
- `cw-dep-bcgait4-phasedir2-staged-fwd` - operator-ordered staged
  phase-RL rung A. Reward was realigned around stride-averaged course,
  EMA overspeed band, clone-banded load/slip pricing, travel floor,
  and phase-locked raw-dialect BC anchor. Preflight bank is green;
  rungs B-D are pre-registered behind rung-A pass gates.
- Stance plant-150 arm remains blocked on the rise-bank residue above.

## Current findings

- The shipped hierarchy in `rl_docs/DOWNLOAD_ANSWER.md`
  (`footlow2_hard1` + `bcgait1_hard1`) is still the fallback product
  baseline, but its evidence is old-plant: the measured tibia-150
  session gate hard-fails while matched 128 mm control passes.
- The convention leak explains the bank breakage, not the quad commits.
  Walk banks are green after the repair; rise-family residue is a real
  tibia-150 recalibration problem.
- The full-heading phase-RL verdict from `phasedir1` is env-confounded
  by the corrupted sim. The zero-RL phase clone still passed the
  direction-first curriculum; staged phase-RL is the active retest.
- Coxa geometry sweep says coxa length is a yaw-margin/scrub lever,
  not a walking-speed lever.

## Track snapshot

- `joystick`: mainline. Plant-150 walk fix and staged phase-RL rung A
  are live; rise-bank cleanup is the next code unblocker.
- `amp`: charter adopted; M0 infrastructure is next.
- `arch` / `dynrep` / `quad` / `turn` / `multitask`: secondary unless
  they directly serve rise+walk download readiness or are explicitly
  ordered.
- `nobc`: from-scratch gait line is stopped; exploration, not reward,
  was the blocker.

## Doc rules

Keep this file under 100 lines. Replace stale status, do not append
history. Use `RL_LOG.md` for one-line cycle history and
`rl_docs/runs/` for run facts. Long audits belong in `archive/`.
