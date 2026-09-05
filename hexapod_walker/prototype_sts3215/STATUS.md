# STATUS - campaign dashboard

Last updated: 2026-09-05 ~05:4x. Operator-facing dashboard, not a
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
  teacher-ceiling-bound.
- `standwalk`: phase-scheduled multi-teacher canary grid (4 arms,
  `...-multiteach-b{05,10}{,-s1}`) — seed0 half (b05/b10) FAILed
  (matches ~20-arm pattern); seed1 half IN FLIGHT on another cycle —
  see Track Snapshot.

## Track Snapshot

- `todaypolicy`: DONE for 08-30 (bundle packaged, GO). Optional: swap
  walk role if a walkteach-lineage export beats MLP-singleframe on the
  identical UX suite; learned-vs-scripted tuck A/B.
- `standwalk`: reward/architecture lever search for steering is
  EXHAUSTED (~22 arms now, all FAIL/CLOSED incl. the literal DONE-gate
  read on mlcontprice8); frozen `cap29-stdwalklo-hi{,-s1}` remains the
  reference. The last surviving lever, a phase-scheduled multi-teacher
  BC-anchor mechanism, FAILed both seed0 doses (blend 0.5 and 1.0) on
  the family's own probe_turn_authority gate — pure-turn regressed
  21-48% past the 10% cap, combined-tick didn't beat the comparator on
  both signs. Seed1 pair still training (another cycle). If it
  matches, the axis closes for good; next moves are a genuine gait-
  structure change (not another magnitude rescale) or a DONE-gate
  turn-authority renegotiation — both deferred to a dedicated design
  pass, not rushed. Details: `rl_docs/tracks/standwalk/STATUS.md`.
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
