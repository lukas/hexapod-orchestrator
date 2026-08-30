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
4. `walkcurr` - OPEN/BLOCKED: prior-free PPO walking remains a separate
   research question. Do not use BC/gait-clock shortcuts here.
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

Evidence: local full-mesh hybrid demo
`logs/manual_drive/cw_walk_allheading_mlp_singleframe_stdanneal_hybrid_tuck_ux_human28/`
completed stand -> walk -> lower with no termination, no sacrificed
legs, `walk_progress_ratio=0.418`, `course_err_1s_med_deg=2.57`,
`wrong_course_frac_1s=0.0`, `cur_max_a=2.64`. It is stable and
directionally obedient, but still underpowered; speed authority is the
weak axis.

Exported walk artifact:
`linux_control/policies/walk_allheading_mlp_singleframe_acq1_stdanneal.json`.

## Active Training

- `cw-walkteach-scripted-allhead-acq12m{,-s1}` are RUNNING after the
  2/2 canary pair passed. They are the live best bet for a more
  joystick-authoritative walk submodel.
- `dualbc3-dagger-anchor14coef1-acq8m{,-s1}` passed its walk-own-scope
  read, but mixed sit -> rise -> walk -> lower evals errored and need
  triage before more single-policy spending.

## Track Snapshot

- `todaypolicy`: package a named composed bundle, compare scripted vs
  learned tuck stand/lower, keep GO/NO-GO current.
- `standwalk`: wait for walkteach acq12m and dualbc3 mixedsession
  triage before the next single-policy distillation spend.
- `walkcurr`: only prior-free mechanisms; no gait prior.
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
