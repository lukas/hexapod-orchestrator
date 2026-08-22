# STATUS - campaign dashboard

Last updated: 2026-08-22 UTC. This is the operator-facing dashboard,
not a history file. If this conflicts with `CURRENT_TRUTHS.md`, that file
wins. Run-level evidence lives in `rl_docs/runs/`, `RL_LOG.md`, and W&B.

## WAITING-ON

- [operator] Fast-gait fork (since 08-21 ~23:5x UTC, still open): a
  4th lever is now refuted. `cw-dep-bcgait3-speedbc1-cont1` (the
  operator's +4M "just keep training" order, fb 20260822T000318Z)
  FINISHED and FAILED worse than its parent: rollout reward "recovery"
  was purely episodes getting shorter (per-tick reward stayed
  net-negative); our own pinned-speed panel on the final checkpoint
  shows 48/48 episodes falling (parent was 34/48), a new sacrificed-leg
  pathology, and direction/speed obedience unimproved. A 5th lever —
  the operator's 08-22 gait-phase/direction-first order
  (fb_20260822T000627 + focus note) — was executed same-night as
  `cw-dep-bcgait4-phasedir1` and ALSO FAILED as an RL lever: 2M PPO on
  a phase-conditioned clone drifted back to the overspeed-forward
  attractor and lost rear headings (matched clone control: dir_err med
  35.6->67.3, speed 0.068->0.139, slip/m 1.81->4.17) — though the
  phase input kept ZERO falls (unlike every prior fast-RL arm). BIG
  POSITIVE: the phase-conditioned BC CLONE ITSELF
  (`ppo_goal_cw_bcgait_init_fullprof_phase1`, committed) passes the
  operator's ENTIRE direction-first curriculum with ZERO RL at the new
  measured plant: all fixed headings incl. rear (prog 0.65-0.76,
  slip/m 1.6-2.0, zero falls) AND irregular heading changes + stops
  (prog 0.70-0.78, zero falls) at fixed 0.08 cmd (SKILLS row).
  Refuted RL levers: faster cadence, k_walk_cmd_track,
  speed-obs+charges, more training steps, phase-obs+fixed-speed.
  Operator decision: adopt the BC clone as the fast-gait candidate
  (next rungs: DR hardening panel, board-side command-gated phase
  clock in the runner), order a different RL pricing, or park.
- [operator, bench-parked] Calibrated plant values (updated 08-22):
  the operator's measured-tibia commit (a4beb8af, tibia 128->150 mm)
  is now IN the sim plant/gait IK — walk stance stands ~169 mm (was
  ~147). This cycle's teacher grid re-validated the scripted tripod
  clean at the new plant (0.06-0.10 m/s x 4 headings, zero falls,
  slip/m 1.4-2.9). NOTE: every pre-08-22 lineage incl. the download
  answer trained on the OLD 128 mm plant — cross-plant comparisons
  need matched controls, and re-gating the download hierarchy on the
  measured plant is an open [operator] call. Remaining calibration
  READINGS (`calibration_report_*.json`, `geometry_manual.json`) still
  live only on the unreachable robot (fb_20260821T224209).
- [operator] Recover mode flip handling (since 08-20 ~23:00 UTC): the
  recover champion is packaged + sim-gate-verified through the
  deployment runner (see below), but flip (full inversion) is out of
  envelope (0/6 own-DR isolation). Ship recover with flip unsupported,
  or order a flip-hardening arm from s13.
- [operator, bench-parked] Recover-mode hardware items: 185 deg tilt
  envelope inside recover mode only, on-robot transformer compute
  check (torch/ONNX at 25 Hz), level-IMU bias calibration. Parked
  until the robot is back (`rl_docs/RECOVER_DEPLOY.md` blockers 2/4/5).
- Agent-doable queue otherwise empty (no untriaged runs, no open CODE
  items); post-lower contract + bench promotion remain [operator].
  Fleet idle by design: every open fork above is operator-gated.

## Read First

Default startup packet for an agent cycle:

1. `RL_GOALS.md`
2. `CURRENT_TRUTHS.md`
3. `RL_PLAN.md`
4. this file
5. `rl_docs/DOWNLOAD_ANSWER.md`
6. the relevant `rl_docs/tracks/<track>/STATUS.md`
7. `RESEARCH_RULES.md` and `RUN_INTERPRETATION_RULES.md` before launch or triage

Do not broad-sweep `archive/`, review bundles, `RL_LOG.md`, or generated
`rl_docs/runs/` unless answering a specific historical/run question.

Robot-control/web edit loop: use `make robot-check`, `make robot-unit-check`,
`make robot-status`, and `make robot-deploy` from this directory
(`linux_control/dev_loop.sh`; details in `linux_control/README.md`). These
helpers do not move the robot; use `make robot-resolve` for a temporary IP
when `hexapod.local` is flaky rather than hard-coding one.

## Current Ruling

SIM SPRINT remains binding: while the physical robot is off the bench for
repair, the single deliverable is reliable rise + walk in MuJoCo that is
ready to download when the robot returns. Bench-only actions stay parked.
Non-hw research tracks launch only when they directly serve this sprint or
when the operator explicitly orders them.

## Download Answer

Unchanged: use the hierarchical session composition in
`rl_docs/DOWNLOAD_ANSWER.md`:

- stance: `ppo_goal_cw_stand_footlow2_hard1`
- walk: `ppo_goal_cw_dep_bcgait1_hard1`
- session controller: per-mode re-anchor, entry slew on, STOP routes to stance hold, rot60 wrapper default-on

Bulk held-out session gate: det 0.967, sto 0.853 across n=600 fresh
sessions. Single-model distills remain worse. Known shipping gaps are
post-lower rise, takeoff roll transient, and unproven learned stand-up on
hardware.

## Live Work

Nothing training. `cw-dep-bcgait3-speedbc1` (08-21 speed-conditioned-BC
fast-gait lever) and its operator-ordered +4M continuation `-cont1`
both FINISHED and FAILED; `-cont1` FAILED WORSE (48/48 falls vs
parent's 34/48, new sacrificed-leg pathology, no obedience gain — the
reward "recovery" was the predicted episode-length artifact, not real
behavior). The operator's 08-22 gait-phase/direction-first order was
executed the same night (`cw-dep-bcgait4-phasedir1`, teacher grid +
phase clone + clone preflight + 2M RL + matched-control gate all in
one cycle): the RL arm FAILED (overspeed attractor returns, rear
headings lost — but zero falls, the phase input works as an
anti-collapse anchor), while the phase-conditioned BC clone PASSED
the full direction-first curriculum with zero RL (see WAITING-ON +
SKILLS). Five fast-gait RL levers now refuted (cadence, tracking
price, speed-obs+charges, more steps, phase-obs+fixed-speed); fork is
operator-gated with a concrete zero-RL candidate on the table. Fast
walking itself still exists (`fastbc1`: zero falls, straight, 2x
overspeed); the deployed answer is untouched. The operator's 08-21 from-scratch ANTI-SLIP
walking experiment (order 20260821T133626Z) ran and FAILED honestly:
`cw-nobc-slipwalk1-r1` (no BC anchor, one fixed forward command, no speed
target, hard structural loaded-slip charge, anti-park travel floor) froze
— 0.001 m of travel per 15 s episode, 0.34 m of foot scuffing, four legs
unused, zero falls only because nothing moved. Importantly the reward was
NOT the culprit: the new SLIPWALK MDP_PREFLIGHT bank (green before launch)
prices real walking 300-2000 points above marching, parking and skating
under that exact stack, so this is an exploration failure from a blank
init. Sub-line stopped per the operator's own instruction; the new
default-off reward pieces stay in the repo. Details:
`rl_docs/tracks/nobc/STATUS.md`. DOWNLOAD_ANSWER unchanged.

## Current Findings

- Product baseline is still the stance/walk hierarchy above.
- Fast gait, full history compressed (details: CURRENT_TRUTHS + `rl_docs/tracks/hw/STATUS.md`): the raised servo profile destabilizes every WARM-STARTED/transplanted policy (4-way A/B: train-through + ramp-in x mid + full dose all FAIL identically); a fresh BC-INIT clone of the native-cadence teacher survives the full profile (`fastbc1` PASS but 2x overspeed); FIVE RL levers to make it obey are refuted (faster cadence at teacher level, k_walk_cmd_track, speed-obs+charges, +4M more steps, phase-obs+fixed-speed). NEW 08-22: the phase-conditioned BC clone with ZERO RL passes the whole direction-first curriculum (see WAITING-ON + SKILLS) — the standing fast-gait candidate is now imitation-only.
- Post-lower rise remains the main stance/session contract decision: `postlower4` looks better only under remaining-rise semantics; promotion requires an operator contract call.
- Recover/tangle: REOPENED by operator order 08-20 and made sim/deploy-ready the same cycle. Champion `predictive1b-pop3-s13` is packaged (policy zip + frozen encoder, relocatable loader — the zip alone is NOT loadable off-pod), the deployment runner obs contract (16x90 predictive context, plant-relative q, entry-hold reset history, LEVEL tilt ref, manual-command gating, stance-hold handoff) is implemented and test-locked, and the 23-rung ladder run THROUGH the runner reproduces the training-path gate exactly: DR-0 21/23 (misses: zero = documented scoring false-negative, flip = genuinely weak), own-DR 22/23 (flip only). Flip is out of envelope: 0/6 in a seed/contract isolation probe — not caused by the deployment contract. Recovery ships as an ADDITIONAL operator-requested mode; the rise+walk download answer is unchanged. Package + contract + blocker list: `rl_docs/RECOVER_DEPLOY.md`.
- Coxa geometry sweep says coxa length is a yaw-margin/scrub lever, not a walking-speed lever; no sim pivot follows from it.

## Operator Gates

Open decisions that should not be resolved by autonomous doc rereads:

- Post-lower contract: accept remaining-rise semantics generally, and decide whether to promote `postlower4` over `footlow2_hard1`.
- Fast gait: OPEN — five RL levers refuted (see WAITING-ON); choose: adopt the zero-RL phase clone as the candidate (then DR panel + board phase-clock runner CODE), a new RL pricing, or park.
- Measured plant: decide whether to re-gate/re-harden the download hierarchy on the new tibia-150 geometry (all pre-08-22 checkpoints trained on the old plant).
- Hardware return: bench-promote the hierarchy or fall back to scripted stand/sit glides as appropriate.
- Recover mode: flip handling (ship unsupported vs flip-hardening arm); hardware-side recover items parked for the bench.
- Non-sprint tracks: arch/dynrep/quad/turn/nobc/multitask stay gated unless directly serving rise+walk download readiness or explicitly ordered.

## Track Snapshot

- `hw`: mainline. Fast-gait fork operator-gated after five refuted RL levers; zero-RL phase clone is the standing candidate. Product baseline unchanged.
- `arch`: temporal/unified-controller research has useful partials but no deployment change.
- `dynrep`: causal-transformer/dynamics representation work found partial walking signals but no replacement for the baseline.
- `nobc`: from-scratch gait stays closed. The operator's 08-21 anti-slip/no-speed-target reopening ran one canary (`cw-nobc-slipwalk1-r1`) and it froze; the spec was preflight-proven correct, so the blocker is exploration from a blank init, and the sub-line is stopped.
- `quad`: specialist/party-trick line, not a current sprint deliverable.
- `turn`: rot60/mirror tooling is useful, but yaw/turn is not the current blocker.
- `multitask`: pause lifted 08-15, but secondary under SIM SPRINT.

## Doc Rules

Keep this file under 150 lines. Replace stale status, do not append history.
Use `RL_LOG.md` for one-line cycle history and `rl_docs/runs/` for run
facts. Long audits belong in `archive/`.
