# STATUS - campaign dashboard

Last updated: 2026-08-23. Operator-facing dashboard,
not a history file. `CURRENT_TRUTHS.md` wins on conflict. Run-level
evidence lives in `rl_docs/runs/`, `RL_LOG.md`, and W&B.

## Current ruling

The campaign now has three active goals:

1. `joystick` - RL from the scripted gait to joystick control.
   Gate: 60 s randomized joystick script in MuJoCo, zero falls,
   directions followed, slip/m within the teacher band.
2. `amp` - from-scratch AMP program (`rl_docs/AMP_LOCOMOTION.md`,
   no Isaac Lab). Gate: milestone M5, MuJoCo cross-engine transfer.
3. `cpg` - Berkeley-style low-dimensional gait search. Gate: a saved
   parameterized controller passes contextual walking/turning/stopping
   tests with zero falls and low slip; any teacher swap is A/B tested.

The loop works until all gates are green: no operator pauses and
tools get built in-cycle. Most visible operating rule: reward and eval
must agree. If reward rises while eval is unsatisfactory and flat/down,
audit reward/eval/simulator alignment before more same-recipe seeds or
longer budget. Continue only when reward and eval improve together, or
after an explicit alignment fix. Out-of-scope runs are operator-kick
only.

## WAITING-ON

- [code] Semantics bank residue: the 08-21/22 bank collapse was
  root-caused to 30660b51, which leaked the robot's absolute-tibia
  knee convention into MuJoCo's femur-relative hinge frame. Boundary
  repair landed in `linux_control/sim_gait_compat.py`; bank is down
  to 7 true tibia-150 recalibration failures. Re-minting the rise
  reference turned out NOT to be a stale-file fix: the scripted
  open-loop belly->plant blend in `extract_rise_ref.py` now falls on
  every seed at tibia-150 (a timing retune makes it worse, not
  better) — it needs an IK/foot-anchored blend. Unblocks
  `cw-stand-footlow2-plant150-1`.
- [operator, bench-parked] Physical promotion and calibration readings:
  the measured-plant numbers still live on the robot, and hardware
  promotion waits until bench work resumes.
- [operator] Recover mode: decide whether to ship flip unsupported or
  order flip-hardening. Hardware-side recover checks are parked.

## Live work

- `cw-dep-bcgait1-plant150-1` - PASSED(core): walk champion
  re-hardened on tibia-150, 0/6 falls DR-0+own-DR, session back-fall
  fixed; promoted as the walk half of the tibia-150 deploy pair.
- `cw-dep-bcgait4-phasedir2-staged-fwd` - rung A FAILED its
  pre-registered progress floor (0.836x clone < 0.9x) despite zero
  falls/6-6 gait/better dir_err; root cause: overspeed/loadslip
  charges price stochastic per-tick noise, not stride-mean behavior.
  Rungs B-D withheld pending a stride-EMA repricing.
- `smoke-amp-asymcritic-mjx` - PASSED: `--asym-critic` ported from the
  CPU trainer to the GPU/Warp trainer (AMP M0), verified on-pod.
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
- `amp`: M0 IN PROGRESS — asym-critic ported to the GPU trainer this
  cycle; discriminator/motion-library/joystick-env wiring is next.
- `cpg`: **GATE GREEN (08-23)**. Held-out 60 s robust gate: full PASS
  (all 5 panels, zero falls, yaw-trim artifact exported + web-UI/
  drive-controller loaders built), and the teacher-adoption A/B is
  measured: at matched 8M budget the CPG motion library is co-equal
  to teacher_v2 as an AMP style source (cpgv1-acq1b det 1.35/0.77m
  vs style05-budget2 1.21/0.71m, control ~flat vs its own 2M read —
  CPG catch-up real, no superiority claim, no forced teacher swap).
  Track work now maintenance-only; hardware drive is [operator].
- `arch` / `dynrep` / `quad` / `turn` / `multitask`: secondary unless
  they directly serve rise+walk download readiness or are explicitly
  ordered.
- `nobc`: from-scratch gait line is stopped; exploration, not reward,
  was the blocker.

## Doc rules

Keep this file under 100 lines. Replace stale status, do not append
history. Use `RL_LOG.md` for one-line cycle history and
`rl_docs/runs/` for run facts. Long audits belong in `archive/`.
