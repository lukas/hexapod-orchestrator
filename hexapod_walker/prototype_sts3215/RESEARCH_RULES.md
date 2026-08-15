# RESEARCH_RULES — binding agent behavior (operator, 08-10)

How the autonomous loop is allowed to design, launch, stop, and
interpret experiments. Moved out of RL_PLAN.md (which keeps blockers,
queue, architecture, closed moves, Gate 0). Startup reading order:
`RL_GOALS.md` → `CURRENT_TRUTHS.md` → `RL_PLAN.md` → this file (+
`RUN_INTERPRETATION_RULES.md`, the per-run triage checklist) →
`rl_docs/SIM.md`; `rl_docs/SKILLS.md` and `rl_docs/runs/<run>.md`
only for a concrete decision; archive/ only for historical questions.

## Operator orders: obey first, ask after (operator, 08-15 — binding)

An operator-AUTHENTICATED order (operator KICK session, MCP request
carrying the dashboard token, or a repo ruling) outranks every rule in
this file. If it conflicts with a rule, a prior verdict, or the
cycle's judgment, the cycle EXECUTES IT ANYWAY — only typo-level
mistakes, genuine safety violations, unrepairable failing
tests/preflight, or mechanical impossibility block execution, and the
block must name the exact mechanical blocker. The conflict is then
filed as a question in `rl_move/orchestrator/OPERATOR_QUESTIONS.md`;
when the operator answers (operator-stamped feedback or a repo edit),
the next cycle updates this file / CURRENT_TRUTHS.md to encode the
operator's reasoning and closes the question. Full procedure:
ORCHESTRATOR_PROMPT.md "Operator orders: obey first, ask after".

## Prime directive

Your job is to minimize the number of unresolved blockers between
the current robot and reliable joystick control — that count is the
campaign KPI. Do not optimize GPU occupancy. Before training, prove
that the reward and evaluator prefer the intended behavior over
every known cheat. Use short runs to discover mechanisms; use long
runs only to harden behavior already seen. Prefer hardware-derived
questions over generic simulator robustness. Maintain a unified
history-conditioned controller as the target architecture; use
hist16 by default when it is competitive, increase plain-MLP
capacity before adopting MoE, and adopt MoE only after correctly
specified multitask training demonstrates genuine skill
interference. Kill obvious bad runs early. Every analysis must end
in a concrete decision that changes the next experiment or the
system.

**The launch question (every spec, before queueing): if this run
succeeds or fails, does it change what we do before the next useful
hardware test? If the answer is no, do not launch it.** Idle GPUs
are acceptable when the critical path is hardware, specification
work, or code fixes. Do not launch experiments to fill slots.

## Research tracks (operator, 08-11 — binding)

The campaign runs as parallel tracks, defined in
`rl_move/orchestrator/tracks.json` with per-track goals + status
docs in `rl_docs/tracks/`. Every launch carries `--track` (or an
inferable run-name prefix); the launcher tags the W&B run
`track:<id>` and records the track in the ledger.

- **hw** is the MAINLINE: the prime directive above (hardware
  joystick KPI, by any means) is ITS directive, and it has priority
  for pods. The other tracks (arch, nobc, quad, turn, …) are
  parallel research lines that run on excess capacity with their own
  goals — read the track's doc before designing for it.
- **CONTAINMENT: triage of a run fires follow-up jobs ONLY in that
  run's track.** The launch question is asked against the TRACK's
  goal, not always the hardware test. A finding that matters to
  another track is escalated, not launched: record one line in BOTH
  tracks' STATUS.md ("Now") plus `CROSS-TRACK INSIGHT:` in
  your cycle logline, and let the other track's next cycle act on
  it. Cross-track launches are operator-only.
- A verdict that changes a track's story updates THAT track's
  `rl_docs/tracks/<track>/STATUS.md` ("Now"/"Next" sections — keep it
  SHORT, a screenful; detail goes to the linked docs). The top-level
  STATUS.md stays the whole-campaign digest.

## Phases and budgets (launcher-enforced: `launch_run.py --phase`)

- **SPECIFICATION** — no PPO. Validate reward ordering, evaluator
  correctness, command semantics, state/action maps, known cheats
  (trajectory banks, preflights, smokes). Never trains.
- **CANARY** — 0.5–2M steps (cap: guardrails
  `phases.discovery_max_steps`), **mechanism health only**: boot, finite
  optimization, routing/exposure, telemetry, and an improving learnable
  signal. Mature behavior is explicitly not judged. A visible immature
  exploit is an observation, not a behavioral/reward closure.
- **DISCOVERY** — 0.5–2M steps (cap: guardrails
  `phases.discovery_max_steps`), aggressive early video/eval. The
  question is binary: did qualitatively correct behavior emerge?
  Stop quickly on a known exploit.
- **ACQUISITION** — 10–40M from-scratch learning after a healthy canary,
  with evidence naming the canary and a comparable full-budget precedent.
  Judge skill at the pre-registered full-budget checkpoints, not at the
  canary. This phase exists because canary and behavioral discovery are
  different questions.
- **HARDENING** — 10–40M + seeds/DR/endurance/promotion panels, only
  after the mechanism works visibly; requires `--evidence` naming
  where (run/video/preflight PASS).
- **COMPOSITION** — combines already-valid skills/axes; every
  protected parent skill is evaluated against frozen baselines.
- **TRANSFER** — exact deployment contract, hardware-derived
  parameters, supported hardware tests, real logs. Outranks generic
  sim work.

## MDP_PREFLIGHT (before any run that adds/changes a reward or task
mechanism)

`rl_move/tests/test_task_semantics.py` must PASS for that mode under
the FULL reward stack the arm will train with; a skipped bank for
the mode is a launch blocker — build the bank first (SPECIFICATION).
Required orderings, with useful margins:

- RISE: honest six-foot plant > partial honest rise >
  flag-leg/tripod-at-height > freeze > unsafe thrash.
- LOWER: honest lower/sit > partial descent > full-height refusal >
  flag-leg/outrigger cheat > unsafe behavior.
- TURN: commanded yaw in the correct direction > partial yaw >
  fixed natural drift/straight walking > parking (safety terms
  active throughout).
- WALK: useful commanded progress > march-in-place/paddle stall >
  park/refusal — without declaring all physical foot slip a failure.

Every new exploit seen on video gets encoded in the bank BEFORE the
reward is fixed. Every success evaluator must reject known visual
cheats even when the scalar target error is good. A reward/eval bug
discovered after training is a preflight failure, never a reason to
launch a longer run. `preflight.py` (frames + frozen-vs-scripted)
stays for env sanity. [CODE, queued] Every new metric ships
machine-readable semantics: description, unit, direction
(higher/lower/target/diagnostic), valid modes, promotion status,
caveats.

## Designing runs

- **REPEALED by operator, 2026-08-15 (~18:20 UTC, relayed via
  authenticated Cursor session): the one-variable-per-run rule.
  Multi-variable/coupled bundles are permitted when the operator
  orders them or the cycle judges the coupling necessary;
  pre-registration and honest verdicts still required.** The
  historical rule read:
  > A **DIAGNOSTIC** run establishes causality or tests one
  > mechanism: one variable per run, off the relevant line's
  > champion, short discovery budget when the behavior is new,
  > matched-parent control mandatory for injected axes.
  The rest of the two-experiment-type framing stands: a DIAGNOSTIC
  run still runs off the relevant line's champion with a short
  discovery budget when the behavior is new, and matched-parent
  controls remain mandatory for injected axes. An **INTEGRATION**
  run (e.g. the unified-controller flagship) answers "does the
  complete controller work?" and may intentionally combine
  already-VALIDATED ingredients — but never pretend it isolates
  causality, and never use it to sneak in an unvalidated ingredient.
- Pre-register the gate and BOTH outcomes (if-true / if-false)
  before launch.
- **Two misses in the same BEHAVIORAL CLASS = change the hypothesis
  or the task specification — never the coefficient or the step
  count** (k=5,10,20,40 on the same penalty has never worked here).
- Warm starts: ent 0.001, inherited std, `--asym-critic`;
  `--no-canary` on single-skill lineages, canaries ON for
  multi-skill. From scratch: std 1.0, ent 0.005–0.01,
  target_kl 0.02. A climbing std is a health alarm.

## Judging runs

- **Work `RUN_INTERPRETATION_RULES.md` (operator, 08-10) BEFORE any
  deep analysis**: 8 ordered questions (learning happened? task — not
  just reward — moved? held-out eval? video physically correct?
  beat the frozen parent under identical conditions? protected
  skills survived? behavior trajectory over checkpoints? is more
  training even justified?) + a classification table mapping
  training/eval/video to the verdict (FAIL / reward-spec bug /
  generalization failure / evaluator loophole / skill interference /
  PASS / transfer failure). Stop at the first failing question;
  reward is never evidence by itself.
- Video is the promotion standard. Name pathologies bluntly (flag
  leg, dragging, skating, jitter, march-in-place). A checkpoint that
  scores well but looks wrong means the METRIC is the bug. ≥12
  episodes (det+sto), at DR 0 AND the run's own DR, 15 s horizon.
- **Phase scope wins before this checklist.** A CANARY can only receive
  `CANARY PASS`, `CANARY FAIL - INFRASTRUCTURE`, or `CANARY FAIL -
  MECHANISM`; it cannot close a skill, behavior, architecture, or reward
  recipe. ACQUISITION is judged at its registered budget unless a separate
  early-kill condition was pre-registered.
- **For DISCOVERY and later behavioral verdicts, a KNOWN exploit in video
  is a complete verdict**: "STOP —
  reward/eval specification bug", one line, no forensic essay, no
  continuation, no re-run with more steps.
- **Matched-parent control**: any eval with an injected physics/
  sensor axis compares the child against the frozen parent under the
  IDENTICAL injection — `eval_checkpoint.py --baseline <parent.zip>`.
  A child-vs-clean-parent verdict is invalid.
- **Behavioral-impossibility kill** (don't wait for a plateau or the
  two-miss rule): kill a stand-up arm when correct success is still 0
  after the discovery window AND a known cheat dominates video AND
  the cheat's return rivals the desired path; kill a turning arm when
  yaw output stays command-invariant despite adequate reward
  separation.
- **A gate discovered to measure the wrong thing invalidates every
  conclusion that depended on it** until those runs are re-evaluated
  under a corrected gate (simplification review §12). Verdicts do
  not survive their evaluator.
- DIG-IN is reserved for genuinely discriminative cases: sim/real
  disagreement, unexpected regression on a correctly specified task,
  or two competing causal hypotheses implying different next actions.
- Wander/endurance is judged on along-path progress, never net
  start-to-end displacement.
- Driving-line runs must pass the JOYSTICK GATE (`eval_drive`:
  0 falls across the direction panel + flip stress). Hardware
  candidates additionally pass Gate 0 (RL_PLAN.md); promotion is
  judged on physical metrics, never one reward scalar.

## Reward routing

- GLOBAL terms = safety/limits/smoothness only; everything else is
  mode-specific. Income must make doing-nothing (parking, freezing,
  hovering, refusal) worth less than reasonable progress on the
  commanded skill BY CONSTRUCTION — audit it, don't assume it (the
  walk park attractor and the rise/lower freeze plateau were both
  this bug).

## Process

- Launches only via `launch_run.py` (capacity, code-SHA gate,
  ledger, phase gate). Ledger edits only via `launch_run.py update`.
  One RL_LOG line per cycle via `ops.sh logline`.
- Refills serve the BLOCKER LIST, not occupancy (reverses the 08-09
  "idle pods are the failure" order). Design questions ON THE
  CRITICAL PATH with a plausible answer get assume-and-go (log
  "## ASSUMPTION (operator to review)"); never invent a peripheral
  run to fill a pod.
- Hardware-derived evidence outranks generic sim robustness. A
  closed hypothesis reopens because of new PHYSICAL evidence (tape,
  current traces, loaded ladders), never because compute is idle.
- Never infer importance from how many lines a topic occupies in
  RL_LOG or the archive; CURRENT_TRUTHS and the current blocker list
  outrank historical token volume (simplification review §12).
- Every analysis ends in a decision that changes the next
  experiment, the task specification, the simulator, the deployment
  gate, or the hypothesis. Otherwise stop analyzing.
