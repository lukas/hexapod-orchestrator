# Walking plan — two parallel physical outcomes

Purpose and priorities: `RL_GOALS.md` (Lukas, 2026-09-08). Method registry:
`rl_move/orchestrator/tracks.json`. Current evidence: `CURRENT_TRUTHS.md`,
the state ledger, and `rl_docs/tracks/<track>/STATUS.md`. History belongs in
`archive/`, `RL_LOG.md`, and generated run docs. Keep this plan under 150 lines.

## Outcomes and methods

1. **`any_means`: smooth physical joystick walking by any effective means.**
   Scripted gaits, CPG search, demonstrations, BC, AMP, RL and composed
   controllers are valid. Deliver usable walking to improve physical builds
   while harder research continues.
2. **`rl_only`: the same physical outcome, learned entirely through RL with
   no demonstrations anywhere in the walking policy's training lineage.**
   A teacher used only during training still disqualifies that lineage.

| Method IDs | Parent outcome |
|------------|----------------|
| `joystick`, `amp`, `cpg`, `standwalk`, `assistfade`, `todaypolicy` | `any_means` |
| `walkcurr` | `rl_only` |

Method gates remain useful evidence with their existing thresholds. They are
not seven independent product requirements. One policy for sit/rise/walk/lower,
AMP's full pipeline, and fault tolerance are optional approaches/extensions;
physical delivery does not wait for all of them. Simulation or packaging
PASS is not physical acceptance of either outcome.

## Startup packet

1. `RL_GOALS.md` — purpose, demonstration boundary, physical acceptance.
2. `CURRENT_TRUTHS.md` — accepted facts and run verdicts.
3. This file, the live ledger, and the relevant method's track journal.
4. `RESEARCH_RULES.md` + `RUN_INTERPRETATION_RULES.md`.
5. `rl_docs/COMMANDS.md` and the applicable hardware runbook for the agent
   that owns a physical step.

## Goal 1 work: make the physical builds useful

1. Select the best supported controller for the current build from existing
   scripted, searched or learned candidates. Check its model/control contract
   and recorded command limits; do not rerun already proven recipes simply
   to fill capacity.
2. Prepare a named controller/build bundle, calibration and runtime checks,
   and a bounded joystick trial with explicit acceptance criteria. Use
   `todaypolicy` for delivery/handoff work; a scripted baseline is valid.
3. Hand physical trials to Robot Lab's serialized guarded runner. Record
   video, requested/achieved motion and telemetry across headings, speed,
   yaw, starts and stops. Establish a useful physical baseline early.
4. Fix the measured limiting factor — mechanics, calibration, command
   handling, gait, model fidelity or training — and compare against that
   baseline. Keep physical build iteration moving while Goal 2 learns.

## Goal 2 work: clean RL discovery through physical transfer

1. Audit policy ancestry and training inputs before accepting a candidate.
   Continue only a clean RL lineage: no BC initialization/anchor, AMP/demo
   prior, teacher targets, assisted-policy distillation or scripted gait
   residual. `walkcurr` also retains its no-gait-clock/no-motion-prior contract.
2. Use the current ledger and mechanism evidence to select the next justified
   prior-free experiment. Easy physics and curricula are acquisition tools;
   success there does not prove realistic walking or physical transfer.
3. Progress from walking discovery to command range, smooth transitions and
   realistic model/actuator conditions, with held-out behavioral evidence.
4. Export and validate the clean policy/runtime, then hand off a bounded
   physical joystick trial under the same acceptance standard as Goal 1.
   Calibration and physical measurements can be shared; demonstration-trained
   weights and gait supervision cannot cross into this lineage.

## Allocation and interpretation

- Pursue both outcomes in parallel within existing guardrails. The earlier
  easy-sim primary-GPU focus is method history, not a prerequisite that can
  block Goal 1's delivery or justified supporting work. No cap changes or
  automatic cancellation/relaunch of existing experiments follow from this plan.
- Every launch or engineering step states its parent outcome, method, current
  gap, hypothesis and required evidence. There is no finish-all-methods rule.
  Keep available capacity supplied with justified runnable work; do not invent
  filler runs or reopen closed recipes without a new supported mechanism.
- Reward/eval agreement first. Bad eval plus rising reward means an objective,
  evaluator or simulator audit; it never automatically justifies a seed sweep.
  Continue learning only when the interpretation rules and evidence support it.
- New PPO/MJX policies use mesh-family 100 Hz unless a registered exception
  says otherwise. Preserve model-family and control-rate provenance at transfer.
- Missing tools are engineering work. Tests follow `RESEARCH_RULES.md`:
  fast mechanics checks; behavioral hypotheses use measured runs and evals.

## Ownership and reporting

Cloud RL cycles prepare candidates and evidence; Robot Lab owns serialized
physical experiments. Standing authority covers observed bounded remote
motion, calibration, deployment and recovery within the active task. Follow
root `AGENTS.md` and `EMERGENCY_HANDLING.md`; ask for hands-on help only when
fresh observations cannot establish or restore normal state. Spend/capacity
increases beyond guardrails remain operator-owned.

Report each parent outcome separately from its method milestones. Track
journals and the ledger retain historical results, including closed recipes;
this reorganization does not alter them. State the best physical evidence,
remaining joystick limits and next measurable step for each outcome. Do not
claim physical success from a MuJoCo PASS or a controller export.

## Documentation discipline

Replace stale narrative with current state. Budgets: `STATUS.md` <=100 lines,
track STATUS <=120, this file <=150, `CURRENT_TRUTHS.md` <=80. One `RL_LOG.md`
line per cycle via `ops.sh logline`. Long audits go to `archive/`.
