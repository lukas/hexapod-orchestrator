# STATUS - campaign dashboard

Last updated: 2026-08-30 ~09:4x PT. Operator-facing dashboard, not a
history file. `CURRENT_TRUTHS.md` wins on conflict. Run-level evidence
lives in `rl_docs/runs/`, `RL_LOG.md`, and W&B.

## Current Ruling

The campaign has six registered tracks in
`rl_move/orchestrator/tracks.json`.

1. `joystick` - GATE GREEN (08-23): legacy RL-from-scripted-gait
   joystick champion `stotight45-seed13` passes the 60 s randomized
   MuJoCo joystick gate with zero falls. Hardware drive is
   operator-owned.
2. `amp` - GATE GREEN at M5 (08-23): AMP from-scratch sim goal met by
   the `phasehz11_s29` family. M6 hardware transfer is operator-owned.
3. `cpg` - GATE GREEN (08-23): parameterized CPG controller passes its
   contextual walking/turning/stopping gate; maintenance/adoption
   comparisons only.
4. `walkcurr` - RETIRED (08-31): honest DONE-negative scope finding.
   Both final literature-wave seeds (`litrep-box-s0/-s1`, 150M each)
   plus every prior non-BC mechanism/architecture class land the same
   static-stand basin. Prior-free discovery alone does not escape it
   at this budget; walking is carried by `joystick`/`standwalk`'s
   BC-anchored lineages instead. No further agent-initiated arms.
5. `standwalk` - OPEN: continue the hard single-policy goal, one
   mesh/100 Hz policy for sit -> rise -> joystick walk -> lower.
6. `todaypolicy` - NEW (08-30): delivery track for a working
   policy-controlled bundle today, allowed to compose explicit
   policy+state pieces while `standwalk` continues in parallel.

## What Works Today

Best current MuJoCo bundle candidate:
`todaypolicy-mlpsf-tuck-v1` =
scripted-or-learned tuck stand/lower +
`cw-walk-allheading-mlp-singleframe-acq1-stdanneal`.

DELIVERED 08-30: `todaypolicy-mlpsf-tuck-v1` PACKAGED, all TODAY bars
PASS on a fresh controller-side full-mesh regen
(`logs/manual_drive/todaypolicy_mlpsf_tuck_v1_fullmesh/`): 0
terminations, full_mesh, no sacrificed legs, course_err_1s med 2.42 /
p90 6.98 / wrong 0.0, progress_ratio 0.418, cur 2.64/1.886 A. GO for
controller handoff; durable evidence + GO/NO-GO + selector path in
`rl_docs/tracks/todaypolicy/bundle_mlpsf_tuck_v1/`. Still speed-soft
(teacher-ceiling); zero turn authority in this walk diet.

Exported walk artifact:
`linux_control/policies/walk_allheading_mlp_singleframe_acq1_stdanneal.json`.

## Active Training

- `cw-walkteach-scripted-allhead-acq12m{,-s1}` FINISHED 08-30: 2/2
  ACQUISITION PASS incl. the formal joystick gate, but authority is
  teacher-ceiling-bound; `dualbc4_walkteach` teacher-adoption distill
  is running (background CPU, controller).
- `dualbc3-dagger-anchor14coef1-acq8m{,-s1}` mixedsession DONE-gate
  reads did NOT error (08-30 ~17:5x triage): harnesses alive on
  train-0/1, owndr sub-pass computing, session sub-pass pending.
  Partial dr0: walk 0/6 success at ~40% of commanded speed, sto
  collapse. No single-policy RL spend until the session reads land.

## Track Snapshot

- `todaypolicy`: DONE for 08-30 (bundle packaged, GO). Optional: swap
  walk role if a walkteach-lineage export beats MLP-singleframe on the
  identical UX suite; learned-vs-scripted tuck A/B.
- `standwalk`: turn-authority-on-a-BC-anchored-walker still unsolved.
  3 mechanism classes FAILed (turndiet, turnpay/walkteach, turncap+RL)
  and both anchor-coefficient doses (1.0/0.3 off 3.0) FAILed too
  (08-31) — anchor DOSE exonerated. New targeted-gate mechanism
  (`train.bc_anchor_walk_turn_skip`) canary in flight on train-2.
- `walkcurr`: RETIRED 08-31, DONE-negative scope finding (see above).
- `joystick`, `amp`, `cpg`: green/maintenance unless the operator
  explicitly reopens them.

## Waiting On

- `[operator]` Any physical robot motion, bench promotion, calibration,
  or hardware drive.
- `[operator]` AMP M6 hardware transfer.
- `[operator]` recover/flip product decision.

## Doc Rules

Keep this file under 100 lines. Replace stale status, do not append
history. Use `RL_LOG.md` for one-line cycle history and
`rl_docs/runs/` for run facts. Long audits belong in `archive/`.
