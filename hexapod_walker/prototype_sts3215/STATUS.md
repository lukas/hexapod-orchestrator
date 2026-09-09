# STATUS — two walking goals, each in sim and on hardware

Goal structure clarified by Lukas on 2026-09-08. This is an operator-facing
digest, not a live fleet snapshot. `RL_GOALS.md` owns purpose and priorities;
`CURRENT_TRUTHS.md` owns accepted evidence. Consult the state ledger and
track journals for current run/queue status.

## Parent outcomes

1. **`any_means`: smooth joystick walking in sim and physically by any effective means.**
   Use scripted, searched, demonstration-assisted or learned controllers to
   make progress on physical builds now. Methods: `joystick`, `amp`, `cpg`,
   `standwalk`, `assistfade`, `todaypolicy`.
2. **`rl_only`: the same sim and physical outcome, learned entirely through RL with
   no demonstrations anywhere in the walking policy's training lineage.**
   Method: `walkcurr`. Random initialization followed by BC/AMP or scripted
   gait assistance belongs to `any_means`, even if assistance later ends.

Both proceed in parallel. Each needs an interactive joystick sim demo and
viewable video as well as physical walking evidence. Report readiness, demo
link/launch command and remaining limits separately for each deliverable.
The candidate below has recorded sim evidence with unresolved command limits;
this digest does not establish a complete sim demo for either goal.
Neither whole outcome is established by the simulation
or packaging evidence summarized below. Physical acceptance needs a named
build/controller, a bounded joystick trial with video and telemetry, and
reported direction/speed/yaw/start/stop limits; `rl_only` also needs clean
training ancestry. The next delivery step is the best-supported candidate's
measured physical comparison through Robot Lab, after its contract and
readiness checks. It does not wait for every method or a monolithic policy.

## Recorded usable candidate and limitations

`todaypolicy-mlpsf-tuck-v1` was PACKAGED 08-30 with all TODAY bars passing on
a fresh controller-side full-mesh regeneration: scripted-or-learned tuck
stand/lower plus `cw-walk-allheading-mlp-singleframe-acq1-stdanneal`.
Evidence: 0 terminations, no sacrificed legs, course error median 2.42° /
p90 6.98°, wrong-course fraction 0.0, progress ratio 0.418,
current 2.64/1.886 A. This was GO for controller handoff, not physical
joystick-walking acceptance. It remained speed-soft with zero turn authority
in that walk diet.

- Bundle evidence and selector path:
  `rl_docs/tracks/todaypolicy/bundle_mlpsf_tuck_v1/`.
- Exported walk:
  `linux_control/policies/walk_allheading_mlp_singleframe_acq1_stdanneal.json`.
- `cw-walkteach-scripted-allhead-acq12m{,-s1}` finished 08-30 with 2/2
  acquisition/joystick passes, but authority remained teacher-ceiling-bound.
- The 09-05 delivery verification flagged a model/regeneration mismatch and
  actor-dependent filter/noise effects. Resolve candidate-specific readiness
  from `rl_docs/tracks/todaypolicy/hardware_delivery/STATUS.md` before transfer.

## Recorded method milestones — not parent-goal completion

- `joystick`: GREEN 08-23 at the legacy 60 s randomized MuJoCo gate
  (`stotight45-seed13`, zero falls); physical drive goes through Robot Lab.
- `amp`: GREEN 08-23 at simulation-transfer M5 (`phasehz11_s29` family).
  Demonstration-assisted; hardware M6 goes through Robot Lab under Goal 1.
- `cpg`: GREEN 08-23 at the contextual walking/turning/stopping gate.
  Its saved controller remains a candidate for measured adoption comparisons.
- `walkcurr`: the 08-31 negative result and the 09-05 bounded easy-physics
  reopening are distinct scopes. Easy-sim acquisition is an intermediate
  milestone for Goal 2, not a reason to delay Goal 1. Use its live journal
  and `CURRENT_TRUTHS.md` for later mechanism findings and closed recipes.
- `standwalk`: the single-policy method remains separate from useful
  controller composition. The recorded steering lever failures are preserved;
  check its journal for later results before proposing another mechanism.
- `assistfade`: rungs 1–4 were closed 09-07 under the tested recipes;
  the 09-09 behavior-gated residual-anneal mechanism (both named levers)
  and 6/6 per-leg reward-shaping addons are now ALSO closed, so every
  tested "fade assist to full raw authority" mechanism has failed on
  mesh/100Hz. Persistent BC-anchor rung 0 remains production-usable and
  is the track's live output. Subsequent mechanism verdicts belong in
  its journal/ledger. Assisted ancestry cannot qualify for Goal 2.
- `todaypolicy`: the 08-30 bundle packaging is a milestone. In the 09-05
  CPU command-envelope study, `env_yawpri` gained yaw at a 55% progress cost;
  shared and fixed-duty time-slice variants were refuted. See the delivery
  journal for limits, model mismatch and measured next steps.

Registry: `rl_move/orchestrator/tracks.json`. Method evidence and queues:
`rl_docs/tracks/<track>/STATUS.md`. No closed recipe is reopened by this
reorganization; there is no requirement to make every method green.

## Ownership and actual waits

Cloud cycles prepare sim evidence and controller handoffs; Robot Lab owns
serialized physical experiments under standing authority and the live
camera/telemetry/abort rules. Routine calibration, bounded motion, deployment
and recovery are not blanket operator blockers. Only concrete hands-on
needs, spend/capacity increases beyond guardrails, or an unresolved product
choice requiring Lukas's decision should be reported as operator waits.
No fresh sim demo or physical verification was performed for this clarification.

## Doc rules

Keep under 100 lines. Replace stale status; put history in `RL_LOG.md` and
generated run docs. Do not infer current fleet activity from this digest.
