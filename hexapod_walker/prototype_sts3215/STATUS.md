# STATUS - campaign dashboard

Last compacted: 2026-08-20 UTC. This is the operator-facing dashboard,
not a history file. If this conflicts with `CURRENT_TRUTHS.md`, that file
wins. Run-level evidence lives in `rl_docs/runs/`, `RL_LOG.md`, and W&B.

## WAITING-ON

- [operator] Fast-gait fork decision: all 4 A/B canaries (train-through &
  ramp-in, mid & full dose) FAILED identically as of 08-20 19:5x UTC.
  Choose: respec with a different lever, or park fast gait and keep the
  current download-answer walk speed.
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

Operator order (test both fast-gait options A and B in sim) is fully
answered as of 2026-08-20 19:5x UTC. All 4 matched canaries **FAIL**
identically: train-through and ramp-in, at mid (750/40/3 deg) and full
(1500/80/5 deg) dose, all collapse instead of repairing (falls trend
worse round-over-round, not toward zero; 0/12 eval episodes ok at each
dose; TERM walk_low_height/fell; dir_err 35-78 deg; slip/m 2.1-11.0 vs a
<=1.6 budget; video shows progressive leg-splay/kicking). The raised
actuator dose itself destabilizes direction-holding and footing,
regardless of onset style or magnitude tested. No pods are running.
WAITING-ON [operator]: fast-gait fork decision (respec with a different
lever, or park and keep the current download-answer walk speed) - see
`rl_docs/tracks/hw/STATUS.md` Operator Gates.

Do not re-kick while the operator-kick cycle or these INTENT/RUNNING rows
exist. Poll `orchestrator_activity` and the ledger.

## Current Findings

- Product baseline is still the stance/walk hierarchy above.
- Fast actuator profile was the speed ceiling; the operator's 4-way A/B (train-through vs ramp-in, mid vs full dose) closes the question: all 4 canaries FAIL identically. No trained dose/onset combo has produced a deployable fast, steerable, low-slip gait.
- `steer6-fasttrack1` full dose: speed improved, direction tracking and slip failed.
- `steer7-middose1` half dose: cleaner than parent under the same profile but still not monotone/in-band and slip remains high.
- V5 fast anti-skate curriculum + `reward.k_loadslip_excess` are implemented and tested.
- Raw raised-profile transplants failed at step-0 B0, so the profile dose itself destabilizes the parent before V5 can help.
- Profile ramp-in FAILED at both tested doses (`fastramp1`, `midramp1`): step-0 B0 already fails at the ramp's fitted start profile, and by 1M at target dose both spin in place (~44-52 deg heading error) with slip well over budget, reproducing steer6-style skating.
- Train-through FAILED at both tested doses (`fastthru1`, `midthru1`): periodic B0 certs show falls trending WORSE not toward zero, and by 1M both dose 0/6 det+sto walk success, TERM walk_low_height/fell, dir_err 35-78 deg, slip/m 2.1-11.0. Same collapse-into-leg-splay pattern as the ramp-in arms.
- The dose itself is the problem, not its abruptness or onset style; the fast-gait fork is closed pending an operator decision (respec with a different lever, or park).
- Post-lower rise remains the main stance/session contract decision: `postlower4` looks better only under remaining-rise semantics; promotion requires an operator contract call.
- Recover/tangle: REOPENED by operator order 08-20 and made sim/deploy-ready the same cycle. Champion `predictive1b-pop3-s13` is packaged (policy zip + frozen encoder, relocatable loader — the zip alone is NOT loadable off-pod), the deployment runner obs contract (16x90 predictive context, plant-relative q, entry-hold reset history, LEVEL tilt ref, manual-command gating, stance-hold handoff) is implemented and test-locked, and the 23-rung ladder run THROUGH the runner reproduces the training-path gate exactly: DR-0 21/23 (misses: zero = documented scoring false-negative, flip = genuinely weak), own-DR 22/23 (flip only). Flip is out of envelope: 0/6 in a seed/contract isolation probe — not caused by the deployment contract. Recovery ships as an ADDITIONAL operator-requested mode; the rise+walk download answer is unchanged. Package + contract + blocker list: `rl_docs/RECOVER_DEPLOY.md`.
- Coxa geometry sweep says coxa length is a yaw-margin/scrub lever, not a walking-speed lever; no sim pivot follows from it.

## Operator Gates

Open decisions that should not be resolved by autonomous doc rereads:

- Post-lower contract: accept remaining-rise semantics generally, and decide whether to promote `postlower4` over `footlow2_hard1`.
- Fast gait after the A/B canaries finish: continue the arm that passes, respec from evidence, or park fast gait and keep the current download answer.
- Hardware return: bench-promote the hierarchy or fall back to scripted stand/sit glides as appropriate.
- Recover mode: flip handling (ship unsupported vs flip-hardening arm); hardware-side recover items parked for the bench.
- Non-sprint tracks: arch/dynrep/quad/turn/nobc/multitask stay gated unless directly serving rise+walk download readiness or explicitly ordered.

## Track Snapshot

- `hw`: mainline. Active work is the fast profile A/B canary set. Product baseline unchanged.
- `arch`: temporal/unified-controller research has useful partials but no deployment change.
- `dynrep`: causal-transformer/dynamics representation work found partial walking signals but no replacement for the baseline.
- `nobc`: from-scratch gait is closed unless new hardware evidence reopens it.
- `quad`: specialist/party-trick line, not a current sprint deliverable.
- `turn`: rot60/mirror tooling is useful, but yaw/turn is not the current blocker.
- `multitask`: pause lifted 08-15, but secondary under SIM SPRINT.

## Doc Rules

Keep this file under 150 lines. Replace stale status, do not append history.
Use `RL_LOG.md` for one-line cycle history and `rl_docs/runs/` for run
facts. Long audits belong in `archive/`.
