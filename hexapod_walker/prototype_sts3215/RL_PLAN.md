# RL Plan - joystick-driven hexapod

Last compacted: 2026-08-20 UTC. This file is the current operating plan.
History belongs in `archive/`, `RL_LOG.md`, and generated run docs. Keep
this file under 250 lines.

## Goal

Drive the real hexapod with a joystick: stand up, sit down, turn, and walk
where pointed, reliably, session after session. Reliability and physical
safety outrank speed and experiment count. Foot slip is not failure by
itself; it is a sim-to-real calibration signal unless it prevents usable
motion or indicates skating/jamming.

## Startup Packet

Read in this order:

1. `RL_GOALS.md` - mission and plain-English framing
2. `CURRENT_TRUTHS.md` - accepted facts and rulings; wins on conflict
3. `RL_PLAN.md` - this operating plan
4. `STATUS.md` - campaign dashboard
5. `rl_docs/DOWNLOAD_ANSWER.md` - current deployable answer
6. relevant `rl_docs/tracks/<track>/STATUS.md`
7. `RESEARCH_RULES.md` and `RUN_INTERPRETATION_RULES.md` before launch/triage

Do not read `archive/`, review bundles, `RL_LOG.md`, or all run docs during
normal startup. Use them only for a specific historical or run-level question.

## Binding Current Ruling: SIM SPRINT

The robot is off the bench for repair. Until the operator says it is back,
the fleet's deliverable is reliable rise + walk in MuJoCo, download-ready.
Every cycle must answer: if the robot were fixed tomorrow morning, what
exactly would we download?

Priority order:

1. Protect and improve the named download answer.
2. Attack the known session gaps: post-lower rise, takeoff roll transient, zero-fall/over-current regressions.
3. Harden the rise/walk champions only when it can change the download answer.
4. Run other tracks only if they directly serve this sprint or the operator explicitly orders them.

Bench-owned items stay parked until hardware returns.

## Current Download Answer

Use the hierarchy maintained in `rl_docs/DOWNLOAD_ANSWER.md`:

- `ppo_goal_cw_stand_footlow2_hard1` for rise/hold/lower
- `ppo_goal_cw_dep_bcgait1_hard1` for tall joystick walk
- session controller with per-mode re-anchor, entry slew, STOP->stance hold, and rot60 wrapper

Measured product baseline: n=600 held-out session gate, det 0.967, sto
0.853. This remains the answer until a run beats it on the relevant gate
and passes the promotion contract.

## Active Queue

Empty. `cw-dep-bcgait3-speedbc1` and its operator-ordered +4M
continuation `-cont1` both finished and FAILED (see hw track STATUS);
four fast-gait speed-obedience levers are now refuted (cadence,
tracking price, speed-obs+charges, more steps). Fast-gait fork returns
to the operator for a new lever. All pods idle; backlog empty.

## Open Operator Decisions

- Post-lower rise contract: adopt remaining-rise semantics and/or promote `postlower4` over `footlow2_hard1`.
- Fast gait: the 08-21 lever (order 20260821T224150Z) and its +4M continuation both FAILED their gates (4th refuted lever); returned to the operator for a new approach.
- Hardware bench promotion after repair: test the hierarchy and decide whether to replace deployed stance/walk fallbacks.
- Recover/tangle redesign: outside SIM SPRINT unless reopened.
- Non-sprint tracks: remain gated unless directly relevant or explicitly ordered.

## Agent-Doable Work

Agent cycles may act without more operator input when all preconditions are
met:

- triage a finished run and write the ledger verdict;
- launch a pre-registered successor whose parent passed its gate;
- fix default-off code required by a selected arm, with tests and snapshot;
- update `STATUS.md`, this plan, a track status, `SKILLS.md`, or `DOWNLOAD_ANSWER.md` when a verdict changes the story.

A pure reread is a no-op. If no launch/code/triage/update is available,
state the specific operator gate and exit.

## Closed Current Conclusions

- Single-policy distills do not beat the hierarchy today.
- Fast profile headroom explains the old speed ceiling but not the complete fast-gait solution.
- Repricing-only attempts have repeatedly failed on several anchored behaviors; change the mechanism or the task, not just coefficients.
- From-scratch gait is closed absent new hardware evidence.
- Recover made real progress scientifically, but it is not in the current download answer.

## Documentation Discipline

Replace stale narrative with current state. Do not append long histories to
active summaries. Suggested budgets:

- `STATUS.md`: <=150 lines
- track `STATUS.md`: <=120 lines
- `RL_PLAN.md`: <=250 lines
- `CURRENT_TRUTHS.md`: <=80 lines
- `RL_LOG.md`: one line per cycle via `ops.sh logline`

Review bundles and long audits live in `archive/`.
