# STATUS - campaign dashboard

Last updated: 2026-08-23. Operator-facing dashboard,
not a history file. `CURRENT_TRUTHS.md` wins on conflict. Run-level
evidence lives in `rl_docs/runs/`, `RL_LOG.md`, and W&B.

## Current ruling

The campaign has three registered goals; two now read GATE GREEN:

1. `joystick` - **GATE GREEN (08-23, assume-and-go)**: RL from the
   scripted gait to joystick control. Gate: 60 s randomized joystick
   script in MuJoCo, zero falls, directions followed, slip/m within
   the teacher band. Champion `stotight45-seed13` passes on 4/4 seeds
   + 2/2 held-out command bases, n=48, zero falls. See
   `CURRENT_TRUTHS.md`; operator override open at
   `OPERATOR_QUESTIONS.md` q_20260822T1730Z.
2. `amp` - from-scratch AMP program (`rl_docs/AMP_LOCOMOTION.md`,
   no Isaac Lab). Gate: milestone M5, MuJoCo cross-engine transfer.
   First full M5 pass landed (tipfrac05) but a same-day correction
   found the champion is NOT zero-fall on its own hazard-free gate
   (2/12) and 5/6-6/7 family checkpoints shared one fall maneuver at
   a fixed held-out episode, traced to the trained push-force range
   (10-25N) rather than turn-in-place/fault. FIX FOUND AND CONFIRMED
   AT BOTH TIERS ON FRESH RETRAINS (08-23 ~10:3x-10:4x): recalibrating
   `dr.ext_push_n` to 5-18N gives 0/12 real falls on the fault+push
   tier (`pushcont1-pushcal518`, vs the untouched range's own 4/12)
   AND on the FULL turn+fault+push composition (`tipfrac05-pushcal518`,
   seed=7: 0/12 real falls, vs `tipfrac05`'s own 2/12, video-confirmed
   clean at the specific episode that toppled 5/6 of the seed batch).
   Seed-robustness: `-seed23` twin PASSES (0/12 falls, matches
   seed7); `-seed13` still in flight. Full `eval_amp_m5` cross-engine
   re-run on the recalibrated checkpoint is DONE and `m5_pass=false`
   (a genuine trade, not a clean promotion): push/fault sections both
   IMPROVE (fault clears its bar for the first time on this lineage,
   12/12 vs 9/12), but walk-slip and yaw-tip both slip just past
   their own strict bars (3.67 vs 3.5; 0.2157/0.2351 vs 0.20) with
   zero falls/terminations and video-clean gait — not yet
   promotable. **BREAK (08-23 ~21:0x): the cadence dose-curve found
   the fix — slowing the gait phase clock 1.33->1.1 Hz (`-phasehz11`,
   single lever) gives the first FULL amp-m5-v1 PASS that survives
   scrutiny: yaw tips 0.1451/0.1453, walk det_prog 0.893 / det_slip
   3.131 at n=28, push+fault green, 0 falls anywhere, strips clean.
   Checkpoint is the M5 candidate champion (SKILLS.md row). Gate
   flips on the 4-seed pass-rate read (seed 17/23/29 twins RUNNING;
   >=3/4 incl. seed-7 original = DONE) — q_20260823T2110Z.**
3. `cpg` - **GATE GREEN (08-23)**: Berkeley-style low-dimensional
   gait search. Gate: a saved parameterized controller passes
   contextual walking/turning/stopping tests with zero falls and low
   slip; any teacher swap is A/B tested. Both named gaps (web-UI
   loader, teacher-adoption A/B) are closed; maintenance-only.

The loop works until all gates are green: no operator pauses and
tools get built in-cycle. Most visible operating rule: reward and eval
must agree. If reward rises while eval is unsatisfactory and flat/down,
audit reward/eval/simulator alignment before more same-recipe seeds or
longer budget. Continue only when reward and eval improve together, or
after an explicit alignment fix. Out-of-scope runs are operator-kick
only.

## WAITING-ON

- [operator] Physical promotion, calibration readings, and hardware
  drive of the joystick/cpg champions: waits on bench access resuming.
- [operator] Recover mode: decide whether to ship flip unsupported or
  order flip-hardening. Hardware-side recover checks are parked.
- (none code-side: the tibia-150 rise-bank/RSI residue that used to
  block stance promotion is CLOSED — see joystick/STATUS.md's
  MEASURED-PLANT GATE BREAK entries.)

## Current findings

- `rl_docs/DOWNLOAD_ANSWER.md`'s shipped hierarchy predates the
  tibia-150 plant fix and the joystick DONE-gate champion; it needs a
  refresh pass before it's presented as the current product baseline
  (not done this cycle — flag only).
- AMP M4/M5's `gait_valid` eval field does NOT zero on a fall
  termination (only on sacrificed legs) — always read `terminated`/
  `term_reason` per-episode (`ops.sh report` already surfaces both;
  do not eyeball the `gait_valid` scalar alone) before calling any
  eval "clean."

## Track snapshot

- `joystick`: **GATE GREEN (08-23)**. `stotight45-seed13` champion
  passes the full 60s randomized session gate 4/4 seeds + 2/2
  held-out command bases, zero falls, n=48. Track work is
  maintenance/hardening-only now; hardware drive is [operator].
- `amp`: M4/M5 first full pass landed (tipfrac05, turn-exposure
  curriculum) then CORRECTED same day: raw per-episode `term_reason`
  (not the `gait_valid` scalar, which never zeroes on a fall) shows
  the champion itself falls 2/12 on its own hazard-free gate, and 5/6
  family checkpoints (7 seeds tested) share ONE fall at the same
  fixed held-out episode (`walk/det/3`, all `tilt_roll`, 32-41deg
  roll peak) — a near-universal hard-maneuver gap, not seed-basin
  luck. DIG-IN queued: replay `walk_det_3.mp4` across the family to
  pin the maneuver, then check its `stress_mix` training exposure.
  Do not promote past the current champion until root-caused. M6
  hardware is [operator].
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
