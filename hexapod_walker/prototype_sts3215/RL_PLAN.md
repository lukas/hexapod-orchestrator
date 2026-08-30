# RL Plan — six registered tracks

Reset by operator 2026-08-21; `walkcurr` added 2026-08-23;
`standwalk` and `todaypolicy` added during the mesh/100 Hz push.
Binding track registry: `rl_move/orchestrator/tracks.json`. History
belongs in `archive/`, `RL_LOG.md`, and generated run docs. Keep under
150 lines.

## Tracks

1. `joystick` — RL from scripted gait to joystick control. Gate: 60 s
   randomized MuJoCo joystick script, zero falls, directions followed,
   teacher-band slip, held-out det+sto DR panels.
2. `amp` — AMP from scratch per `rl_docs/AMP_LOCOMOTION.md`; done at
   M5 MuJoCo transfer, M6 hardware operator-owned.
3. `cpg` — direct low-dimensional CPG/SE2 controller search; teacher
   adoption only by A/B.
4. `walkcurr` — prior-free PPO walking: no gait clock, no BC teacher,
   no motion prior; reward bank required.
5. `standwalk` — keep trying to make ONE mesh/100 Hz policy for sit ->
   rise -> joystick walk -> lower.
6. `todaypolicy` — ship a working policy-controlled bundle today, using
   explicit policy+state composition if that is what works. Does not
   mark `standwalk` green.

Each track has its live Goal/Now/Next page at
`rl_docs/tracks/<track>/STATUS.md`. The loop does not stop until all
registered gates are green. Out-of-scope operator runs get honest
triage but no agent follow-ups.

## Startup Packet

1. `CURRENT_TRUTHS.md`
2. this file
3. the relevant `rl_docs/tracks/<track>/STATUS.md`
4. `RESEARCH_RULES.md` + `RUN_INTERPRETATION_RULES.md`
5. `rl_docs/COMMANDS.md`

## Binding Rulings

- Reward/eval agreement first. Bad eval plus rising reward means
  reward/eval/simulator mismatch or justified continuation, never an
  automatic same-recipe seed sweep.
- No operator pauses except physical robot access and spend approvals.
- Build missing tools/harnesses/banks/models in-cycle and test them.
- New PPO/MJX policies use mesh-family 100 Hz unless a registered
  legacy exception says otherwise.

## Active Queue

### todaypolicy

1. Package `todaypolicy-mlpsf-tuck-v1`: tuck stand/lower plus exported
   `walk_allheading_mlp_singleframe_acq1_stdanneal.json`, full-mesh
   `ops.sh hybriddemo`, `transfer_manifest`, and GO/NO-GO summary.
2. Compare scripted tuck against learned `stand_stancemix_tuckclock_scratch8m`
   stand/lower in the same harness.
3. When `cw-walkteach-scripted-allhead-acq12m{,-s1}` lands, compare it
   against the mlp-singleframe bundle for joystick authority.

### standwalk

1. Let `cw-walkteach-scripted-allhead-acq12m{,-s1}` run and triage the
   authority/readiness gates.
2. Triage `dualbc3-dagger-anchor14coef1-acq8m{,-s1}` mixedsession
   errors before more unified-policy spending.
3. Distill one policy only after the walk source and stance/lower
   teacher are selected by evidence.

### walkcurr

1. Continue only prior-free mechanisms. No BC, gait clock, motion prior,
   or teacher shortcuts.
2. On aligned fail: dig into reward/eval/simulator before seeds.

### joystick / amp / cpg

1. Green or maintenance unless the operator reopens them.
2. Keep their artifacts available as candidates or baselines for
   `todaypolicy` and teachers/control arms for other tracks.

## Inherited Assets

- Scripted tripod teacher: measured tibia-150 plant, 0.06-0.10 m/s,
  zero falls, slip/m 1.4-2.9.
- `cw-walk-allheading-mlp-singleframe-acq1-stdanneal`: best exported
  full-mesh RL walk role today, stable but speed-soft.
- `stand_stancemix_tuckclock_scratch8m{,_s1}` and scripted tuck:
  current tuck stand/lower options.
- `cw-walkteach-scripted-allhead-acq12m{,-s1}`: active candidate for a
  more authoritative all-heading walk.
- MJX/Warp GPU stack, model DR, eval/video, desync, and `ops.sh`
  helpers.

## Operator-Owned Items

- Physical robot motion, bench promotion, calibration, hardware drive.
- Spend/capacity changes beyond guardrails.
- Product choices that require accepting an unsupported recover/flip
  gap.

## Documentation Discipline

Replace stale narrative with current state. Budgets: `STATUS.md`
<=100 lines, track STATUS <=120, this file <=150,
`CURRENT_TRUTHS.md` <=80. One `RL_LOG.md` line per cycle via
`ops.sh logline`. Long audits go to `archive/`.
