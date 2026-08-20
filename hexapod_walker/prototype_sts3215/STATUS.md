# STATUS - campaign dashboard

Last compacted: 2026-08-20 UTC. This is the operator-facing dashboard,
not a history file. If this conflicts with `CURRENT_TRUTHS.md`, that file
wins. Run-level evidence lives in `rl_docs/runs/`, `RL_LOG.md`, and W&B.

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

Latest operator order executed: test both fast-gait options A and B in sim.
Live ledger rows as of 2026-08-20 19:27 UTC:

- `cw-dep-bcgait1-fastthru1` - RUNNING, 1M canary, full 1500/80/5 deg profile, B0 pre-cert waived so PPO can try to repair the step-0 wobble.
- `cw-dep-bcgait1-midthru1` - INTENT, 1M canary, mid 750/40/3 deg profile, B0 pre-cert waived.
- `cw-dep-bcgait1-midramp1` - RUNNING, 1M canary, profile ramp from fitted 350/20/1.5 deg to 750/40/3 deg over the first 500k steps.
- `cw-dep-bcgait1-fastramp1` - RUNNING, 1M canary, profile ramp from fitted 350/20/1.5 deg to 1500/80/5 deg over the first 500k steps.

Do not re-kick while the operator-kick cycle or these INTENT/RUNNING rows
exist. Poll `orchestrator_activity` and the ledger.

## Current Findings

- Product baseline is still the stance/walk hierarchy above.
- Fast actuator profile was the speed ceiling, but neither trained dose has produced a deployable fast, steerable, low-slip gait yet.
- `steer6-fasttrack1` full dose: speed improved, direction tracking and slip failed.
- `steer7-middose1` half dose: cleaner than parent under the same profile but still not monotone/in-band and slip remains high.
- V5 fast anti-skate curriculum + `reward.k_loadslip_excess` are implemented and tested.
- Raw raised-profile transplants failed at step-0 B0, so the profile dose itself destabilizes the parent before V5 can help.
- Profile ramp-in is built and under test in the live canaries above.
- Post-lower rise remains the main stance/session contract decision: `postlower4` looks better only under remaining-rise semantics; promotion requires an operator contract call.
- Recover/tangle work made a real scientific gain, but it is outside the current download answer and remains operator-gated during SIM SPRINT.
- Coxa geometry sweep says coxa length is a yaw-margin/scrub lever, not a walking-speed lever; no sim pivot follows from it.

## Operator Gates

Open decisions that should not be resolved by autonomous doc rereads:

- Post-lower contract: accept remaining-rise semantics generally, and decide whether to promote `postlower4` over `footlow2_hard1`.
- Fast gait after the A/B canaries finish: continue the arm that passes, respec from evidence, or park fast gait and keep the current download answer.
- Hardware return: bench-promote the hierarchy or fall back to scripted stand/sit glides as appropriate.
- Recover/tangle redesign: parked until the operator reopens it.
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
