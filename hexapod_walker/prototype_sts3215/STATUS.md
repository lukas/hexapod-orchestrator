# STATUS - campaign dashboard

Last compacted: 2026-08-20 UTC. This is the operator-facing dashboard,
not a history file. If this conflicts with `CURRENT_TRUTHS.md`, that file
wins. Run-level evidence lives in `rl_docs/runs/`, `RL_LOG.md`, and W&B.

## WAITING-ON

- [operator] q_20260820T2330Z: confirm the fast-gait substitution, AND
  decide the fork now that its pre-authorized successor has also
  FAILED. The 08-20 order (fb 20260820T224241Z) resolved the fork with
  a faster-TripodGait-cadence BC-INIT lever, but that knob FAILED its
  own teacher preflight at every rung; the cycle substituted a fresh
  BC-INIT from the FULL-profile native-cadence teacher instead:
  `cw-dep-bcgait2-fastbc1` PASSED discovery (tall, fast, zero falls,
  direction correct, only overspeeds ~2x). Its pre-authorized hardening
  fix, `cw-dep-bcgait2-fastbc1-track1` (adds `k_walk_cmd_track=1.0`),
  has now FINISHED and FAILED its own gate: the command-tracking price
  made the overspeed WORSE (DR-0 prog_ratio det 1.88x->2.10x, sto
  1.20x->1.76x; own-DR sto 1.12x->1.92x, was in-band, now overspeeds),
  zero falls/clean video unchanged. Per the gate's own text this is
  "wrong lever, STOP" — no further respec without a new hypothesis.
  BLOCKING for the fast-gait sub-line: no agent-doable next step
  exists until the operator either supplies a new lever or parks the
  line (details in OPERATOR_QUESTIONS.md).
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

No runs currently training. The operator's 08-21 from-scratch ANTI-SLIP
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

The 08-20 fast-gait BC-INIT fork remains STALLED on the operator
(q_20260820T2330Z): `cw-dep-bcgait2-fastbc1` PASSED discovery but
overspeeds 2x, and its pre-authorized hardening fix
`cw-dep-bcgait2-fastbc1-track1` FAILED (overspeed got worse).

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
- The dose itself is the problem FOR TRANSPLANTED/WARM-STARTED policies, not its abruptness or onset style. 08-20 order reopened the fork via BC-INIT: the ordered faster-cadence teacher knob was refuted by preflight, but a fresh clone of the NATIVE-cadence teacher under the full profile DOES survive RL fine-tune (canary `cw-dep-bcgait2-fastbc1`: tall, clean 6-leg gait, zero falls, direction correct, but overspeeds command 2x). Its command-tracking hardening fix `cw-dep-bcgait2-fastbc1-track1` FAILED: overspeed got WORSE, not better (det 1.88x->2.10x, sto 1.20x->1.76x, own-DR sto 1.12x->1.92x). That pricing term is the wrong lever; no further respec without a new hypothesis (operator gate, q_20260820T2330Z).
- Post-lower rise remains the main stance/session contract decision: `postlower4` looks better only under remaining-rise semantics; promotion requires an operator contract call.
- Recover/tangle: REOPENED by operator order 08-20 and made sim/deploy-ready the same cycle. Champion `predictive1b-pop3-s13` is packaged (policy zip + frozen encoder, relocatable loader — the zip alone is NOT loadable off-pod), the deployment runner obs contract (16x90 predictive context, plant-relative q, entry-hold reset history, LEVEL tilt ref, manual-command gating, stance-hold handoff) is implemented and test-locked, and the 23-rung ladder run THROUGH the runner reproduces the training-path gate exactly: DR-0 21/23 (misses: zero = documented scoring false-negative, flip = genuinely weak), own-DR 22/23 (flip only). Flip is out of envelope: 0/6 in a seed/contract isolation probe — not caused by the deployment contract. Recovery ships as an ADDITIONAL operator-requested mode; the rise+walk download answer is unchanged. Package + contract + blocker list: `rl_docs/RECOVER_DEPLOY.md`.
- Coxa geometry sweep says coxa length is a yaw-margin/scrub lever, not a walking-speed lever; no sim pivot follows from it.

## Operator Gates

Open decisions that should not be resolved by autonomous doc rereads:

- Post-lower contract: accept remaining-rise semantics generally, and decide whether to promote `postlower4` over `footlow2_hard1`.
- Fast gait: confirm the 08-20 substitution AND supply the next lever (q_20260820T2330Z) — cadence knob refuted by preflight, full-profile BC-INIT canary (fastbc1) passed discovery but overspeeds, and its pre-authorized command-tracking hardening fix (fastbc1-track1) also FAILED (overspeed got worse). No agent-doable next step on this sub-line without a new hypothesis.
- Hardware return: bench-promote the hierarchy or fall back to scripted stand/sit glides as appropriate.
- Recover mode: flip handling (ship unsupported vs flip-hardening arm); hardware-side recover items parked for the bench.
- Non-sprint tracks: arch/dynrep/quad/turn/nobc/multitask stay gated unless directly serving rise+walk download readiness or explicitly ordered.

## Track Snapshot

- `hw`: mainline. The 08-20 fast-gait BC-INIT line is stalled: canary `cw-dep-bcgait2-fastbc1` PASSED discovery (fast/tall/clean, overspeeds), but its hardening fix `cw-dep-bcgait2-fastbc1-track1` FAILED (overspeed got worse, not better). No fast-gait runs live; awaiting operator (q_20260820T2330Z). Product baseline unchanged.
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
