# STATUS - campaign dashboard

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

Keep this file under 100 lines. Replace stale status, do not append
history. One-line cycle history in `RL_LOG.md`; long audits in
`archive/`.
