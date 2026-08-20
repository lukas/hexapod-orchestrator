# STATUS - campaign dashboard

Last compacted: 2026-08-20 UTC. This is the operator-facing dashboard,
not a history file. If this conflicts with `CURRENT_TRUTHS.md`, that file
wins. Run-level evidence lives in `rl_docs/runs/`, `RL_LOG.md`, and W&B.

## WAITING-ON

- [operator] q_20260820T2330Z: confirm the fast-gait substitution. The
  08-20 order (fb 20260820T224241Z) resolved the fork with a
  faster-TripodGait-cadence BC-INIT lever, but that knob FAILED its own
  teacher preflight at every rung (period_scale 0.9/0.75/0.6 all strictly
  worse at native/mid/full servo profile); the cycle executed the order's
  conditional branch instead: fresh BC-INIT from the FULL-profile
  native-cadence teacher (teacher preflight prog 0.76, tall, zero falls)
  as 2M canary `cw-dep-bcgait2-fastbc1`, which PASSED discovery
  (tall, fast, zero falls, direction correct, only overspeeds). Not
  blocking — the pre-authorized hardening continuation
  (`cw-dep-bcgait2-fastbc1-track1`, adds `k_walk_cmd_track`) is already
  RUNNING under the order's own successor clause; details in
  OPERATOR_QUESTIONS.md.
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

Fast-gait fork REOPENED by operator order 08-20 ~22:42 UTC (fb
20260820T224241Z): try the BC gait idea again with a faster TripodGait
cadence, preflight-gated. Executed same cycle:

- CODE: `--tripod-period-scale` knob in `bc_init_gait.py` (default-off,
  bit-exact at 1.0) + `gait@p<scale>` policy specs and slip/height
  fingerprints in `probe_walk_income.py` (+ its env now honors `--set
  bus.*`); tests `test_bc_gait_cadence.py`, all green.
- Teacher preflight grid (3 cadences x native/mid/full profile x
  0.055/0.07/0.10 m/s, forward+crab, 3 seeds): faster cadence is
  STRICTLY WORSE in every cell (e.g. full profile prog 0.76 -> 0.65
  (p0.9) -> 0.57 (p0.75) -> 0.10-0.30 (p0.6); slip/m explodes). The
  ordered knob is refuted at the teacher level — no cadence canary, per
  the order's own preflight gate.
- Same grid PROVES the full profile (1500/80/5 deg) safe for the
  NATIVE-cadence teacher: prog 0.73-0.76 (~2x native realized speed),
  slip/m 1.6-3.0, 147 mm tall, clean 6-leg tripod, zero falls — the
  order's "unless a preflight proves the higher profile safe" branch.
- Fresh clone `ppo_goal_cw_bcgait_init_fullprof1.zip` (md5 e83595fe)
  preflights at teacher level (prog 0.63-0.89 all seeds/dirs, zero
  terminations). 2M canary `cw-dep-bcgait2-fastbc1` finished PASS AS
  DISCOVERY CANARY (not deployable yet): DR-0 det walk 6/6 gait_valid,
  zero falls det+sto, tall clean six-leg video, roll settles (tail
  1.1-2.3 deg), det slip/m med 1.76 (in budget), realized speed 0.117
  m/s (~2x deployed walker), direction correct (wrong_dir frac
  0.04-0.14, no steer6-style spin) — the counterexample to the 4 failed
  A/B transplant canaries. Miss: OVERSPEED (prog ratio med det 1.95 /
  sto 1.30 vs the 0.75-1.25 band; the vel:=ref obs contract gives no
  speed feedback and nothing priced the excess), plus sto slip 3.32 and
  currents above soft ~14.6s/15. Pre-authorized single near-miss
  continuation launched same cycle: `cw-dep-bcgait2-fastbc1-track1`
  (RUNNING on train-7, `--phase hardening`, 5M, warm from fastbc1, adds
  `reward.k_walk_cmd_track=1.0` to price the overspeed) — its own
  pre-registered gate is in the ledger entry. DOWNLOAD_ANSWER unchanged
  unless this hardened child beats `bcgait1_hard1` on the session gate.

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
- The dose itself is the problem FOR TRANSPLANTED/WARM-STARTED policies, not its abruptness or onset style. 08-20 order reopened the fork via BC-INIT: the ordered faster-cadence teacher knob was refuted by preflight (every rung strictly worse at every profile), but the scripted teacher itself at NATIVE cadence is clean and ~2x faster under the full profile (prog 0.76, slip/m 1.6-3.0, tall, zero falls) — canary `cw-dep-bcgait2-fastbc1` PASSED discovery: a fresh clone of that teacher DOES survive RL fine-tune under the profile (tall, clean 6-leg gait, zero falls, direction correct) but overspeeds the command 2x (nothing priced excess speed under the vel:=ref contract). Hardening rung `cw-dep-bcgait2-fastbc1-track1` (adds `reward.k_walk_cmd_track=1.0`) is RUNNING to fix that.
- Post-lower rise remains the main stance/session contract decision: `postlower4` looks better only under remaining-rise semantics; promotion requires an operator contract call.
- Recover/tangle: REOPENED by operator order 08-20 and made sim/deploy-ready the same cycle. Champion `predictive1b-pop3-s13` is packaged (policy zip + frozen encoder, relocatable loader — the zip alone is NOT loadable off-pod), the deployment runner obs contract (16x90 predictive context, plant-relative q, entry-hold reset history, LEVEL tilt ref, manual-command gating, stance-hold handoff) is implemented and test-locked, and the 23-rung ladder run THROUGH the runner reproduces the training-path gate exactly: DR-0 21/23 (misses: zero = documented scoring false-negative, flip = genuinely weak), own-DR 22/23 (flip only). Flip is out of envelope: 0/6 in a seed/contract isolation probe — not caused by the deployment contract. Recovery ships as an ADDITIONAL operator-requested mode; the rise+walk download answer is unchanged. Package + contract + blocker list: `rl_docs/RECOVER_DEPLOY.md`.
- Coxa geometry sweep says coxa length is a yaw-margin/scrub lever, not a walking-speed lever; no sim pivot follows from it.

## Operator Gates

Open decisions that should not be resolved by autonomous doc rereads:

- Post-lower contract: accept remaining-rise semantics generally, and decide whether to promote `postlower4` over `footlow2_hard1`.
- Fast gait: confirm the 08-20 substitution (q_20260820T2330Z) — cadence knob retired by preflight refutation, full-profile BC-INIT canary launched in its place.
- Hardware return: bench-promote the hierarchy or fall back to scripted stand/sit glides as appropriate.
- Recover mode: flip handling (ship unsupported vs flip-hardening arm); hardware-side recover items parked for the bench.
- Non-sprint tracks: arch/dynrep/quad/turn/nobc/multitask stay gated unless directly serving rise+walk download readiness or explicitly ordered.

## Track Snapshot

- `hw`: mainline. Active work is the 08-20 fast-gait BC-INIT line: canary `cw-dep-bcgait2-fastbc1` PASSED discovery (fast/tall/clean, overspeeds), hardening rung `cw-dep-bcgait2-fastbc1-track1` RUNNING. Product baseline unchanged.
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
