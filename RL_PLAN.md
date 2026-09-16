# Walking plan — two parallel goals, each demonstrated in sim and physically

Purpose and priorities: `RL_GOALS.md` (Lukas, 2026-09-08). Method registry:
`rl_move/orchestrator/tracks.json`. Current evidence: `CURRENT_TRUTHS.md`,
the state ledger, and `rl_docs/tracks/<track>/STATUS.md`. History belongs in
`archive/`, `RL_LOG.md`, and generated run docs. Keep this plan under 150 lines.

## Outcomes and methods

1. **`any_means`: smooth joystick walking in sim and physically by any effective means.**
   Scripted gaits, CPG search, demonstrations, BC, AMP, RL and composed
   controllers are valid. Deliver usable walking to improve physical builds
   while harder research continues.
2. **`rl_only`: full-direction joystick gait plus rise/hold/lower in sim and
   physically, learned entirely through RL with no demonstrations anywhere in
   any motion-producing role's training lineage.** A teacher used only during
   training still disqualifies that lineage.

| Method IDs | Parent outcome |
|------------|----------------|
| `joystick`, `amp`, `cpg`, `standwalk`, `assistfade`, `todaypolicy`, `speed` | `any_means` |
| `walkcurr` | `rl_only` |

Method gates remain useful evidence with their existing thresholds. They are
not seven independent product requirements. A monolithic sit/rise/walk/lower
policy is optional, but Goal 2's full clean lifecycle is not: independently
clean RL motion roles may be composed. AMP's full pipeline and fault tolerance
remain optional approaches/extensions; physical delivery does not wait for
all methods. Simulation or packaging PASS is not physical acceptance of either
outcome. Each goal also requires
its own visible, runnable joystick sim demo and video, per `RL_GOALS.md`.
Publish sim progress when ready; neither demo waits for physical completion
or for the other goal. Track the two deliverables separately for each goal.

## Startup packet

1. `RL_GOALS.md` — purpose, demonstration boundary, sim and physical acceptance.
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
   an interactive full-mesh MuJoCo joystick demo plus video, and a bounded
   physical joystick trial with explicit acceptance criteria. Use
   `todaypolicy` for delivery/handoff work; a scripted baseline is valid.
3. Hand physical trials to Robot Lab's serialized guarded runner. Record
   video, requested/achieved motion and telemetry across headings, speed,
   yaw, starts and stops. Establish a useful physical baseline early.
4. Fix the measured limiting factor — mechanics, calibration, command
   handling, gait, model fidelity or training — and compare against that
   baseline. Keep physical build iteration moving while Goal 2 learns.

### Speed path

`speed` owns the operator-requested maximum-sustainable-speed frontier. It
now has two linked phases: preserve the fast mesh/50 Hz frontier, then make its
best gait survive the physical robot. The current priority is the second phase.
Use the failed PS200 physical tape (16.78-degree roll versus 3.32 degrees in
matched simulation) as evidence: search interacting, correlated and asymmetric
model-error combinations, then compare current DR, wider independent DR and a
physical-signature-targeted structured DR curriculum. Keep a frozen parent and
held-out domains. Rank actual displacement together with six-leg gait validity,
falls, slip, roll/pitch, current and direction; commanded speed, cadence and
reward cannot substitute. A robust candidate must retain at least 90% of the
parent's nominal speed while materially reducing the held-out failure signature
before Robot Lab runs the same bounded physical tape. Cloud work remains
simulation-only and cannot claim transfer. `speed` is assisted `any_means`;
clean RL-only speed work stays within `walkcurr` and cannot inherit its weights
or gait targets. Full gates: `rl_docs/tracks/speed/DESIGN.md`.

## Goal 2 work: clean RL discovery through physical transfer

1. Audit policy ancestry and training inputs before accepting a candidate.
   Continue only a clean RL lineage: no BC initialization/anchor, AMP/demo
   prior, teacher targets, assisted-policy distillation or scripted gait
   residual. `walkcurr` also retains its no-gait-clock/no-motion-prior contract.
2. Treat `bundle_rlonly_v2` as a retained forward-walk milestone, not a
   completed Goal 2 result. Its restricted heading envelope and missing
   rise/lower role are the active gaps.
3. Recover a full 360-degree joystick gait on the corrected mesh model at
   50 Hz: 0/+-45/+-90/+-135/180-degree headings, both yaw signs, speed changes,
   stops and restarts, with all six legs and no known-command exclusions. The
   fifteen closed off-axis mechanism classes stay closed; begin with a written,
   genuinely new structural mechanism rather than another dose/seed variant.
4. Train clean RL rise/hold/lower capability from grounded and perturbed starts.
   It may be a separate role composed with the walker, but it cannot use a
   demonstrated/scripted pose path, gait clock, teacher, assisted init or
   distillation. Task rewards, curricula and ordinary role-selection plumbing
   remain allowed.
5. Export and validate the complete clean stack, then demonstrate grounded ->
   rise/hold -> full joystick session -> lower in interactive full-mesh MuJoCo
   plus video before a bounded physical trial. Calibration and physical
   measurements can be shared; demonstration-trained weights and gait
   supervision cannot cross into this lineage.

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
- Hardware-targeted PPO/MJX policies use the corrected mesh family at 50 Hz.
  A 100 Hz run must be registered explicitly as simulation-only and cannot be
  promoted as a robot candidate. Preserve model/control-rate provenance.
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
this reorganization does not alter them. For each goal, report sim demo
readiness/link/launch command and physical evidence separately, plus remaining
joystick limits and the next measurable step for each deliverable. Do not
claim physical success from a MuJoCo PASS or a controller export.

## Documentation discipline

Replace stale narrative with current state. Budgets: `STATUS.md` <=100 lines,
track STATUS <=120, this file <=150, `CURRENT_TRUTHS.md` <=80. One `RL_LOG.md`
line per cycle via `ops.sh logline`. Long audits go to `archive/`.
