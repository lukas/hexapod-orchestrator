# RESEARCH_RULES — binding agent behavior (operator, 08-21 reset)

How the autonomous loop designs, launches, continues, and interprets
experiments. Startup reading order: `CURRENT_TRUTHS.md` →
`RL_PLAN.md` → the relevant `rl_docs/tracks/<track>/STATUS.md` → this
file + `RUN_INTERPRETATION_RULES.md` before launch/triage.

## Operator orders: obey first, ask after

An operator-authenticated order (KICK session, operator-stamped
feedback, repo ruling) outranks every rule here. Execute it; decline
only for typo-level mistakes, genuine safety violations, unrepairable
failing tests/preflight, or mechanical impossibility — never policy
objections. File conflicts in
`rl_move/orchestrator/OPERATOR_QUESTIONS.md` and keep moving; encode
answers back into these docs and close the question.

## Prime directive (operator, 08-21)

The fleet pursues exactly two goals — the `joystick` and `amp` track
gates in `rl_move/orchestrator/tracks.json` — and does not stop until
both are green. Every launch answers: which gap between the current
state and this track's DONE gate does this run close? Idle pods next
to an unmet gate are the failure state; there is almost always a tool
to build, an alignment bank to write, a continuation to fund, or the
next milestone arm to queue. Do not park lines waiting on the
operator: assume-and-go with a recorded assumption. Only
physical-robot access and spend approvals may wait. The operator may
launch out-of-scope runs; triage them honestly, but agent launches go
only to the two tracks.

## Interpretation (operator, 08-21 — full text in
RUN_INTERPRETATION_RULES.md)

Bad evals/canaries with training reward still rising is never a fail:
the run is UNDERTRAINED (continue from the checkpoint) and/or the
reward is MISALIGNED with the evals (fix the reward so its optimum is
the gate behavior, encode the cheat in the semantics bank, relaunch).
A genuine FAIL requires flat learning at adequate budget, or an
aligned reward that still doesn't move the gate. Video outranks
scalars in both directions: exploits mean misalignment, and a
good-scoring bad-looking checkpoint means the metric is the bug.

## Phases and budgets (launcher-enforced: `launch_run.py --phase`)

- **SPECIFICATION** — no PPO. Reward/eval alignment work: semantics
  banks, preflights, evaluators, motion-library validation.
- **CANARY** — <=2M steps, mechanism health only (boot, finite
  optimization, telemetry, an improving learnable signal). Never
  closes a behavior or reward class.
- **DISCOVERY** — <=2M steps, aggressive early video. Question: did
  qualitatively correct behavior emerge? An exploit here = MISALIGNED,
  not a lineage kill.
- **ACQUISITION** — full honest learning budget (10–40M+) after a
  healthy canary; judged at the registered budget, and continuable
  beyond it under the 08-21 ruling while reward and gate metrics rise.
- **HARDENING** — seeds/DR/endurance/promotion panels on behavior that
  already works visibly; requires `--evidence`.
- **COMPOSITION / TRANSFER** — combining validated skills / the exact
  deployment contract. Protected parents evaluated against frozen
  baselines.

## MDP_PREFLIGHT — reward<->eval alignment is mandatory

Before any run that adds or changes a reward or task mechanism, the
mode's `rl_move/tests/test_task_semantics.py` bank must PASS under the
full training reward stack: the intended gate behavior must out-earn
every known cheat (park, freeze, flag-leg, tripod, paddle-creep,
overspeed, sacrificed leg) with useful margin. A missing bank means
build the bank first — that is SPECIFICATION work and it never trains.
Every new exploit seen on video gets encoded in the bank BEFORE the
reward is fixed. This is the mechanism that makes the 08-21 ruling
safe: alignment is proven before budget is spent, so rising reward is
meaningful evidence.

## Designing runs

- `joystick` track: warm-start by default (phase clone / walk
  champion lineage); ent 0.001, inherited std, `--asym-critic`.
- `amp` track: from scratch by design (std 1.0, ent 0.005–0.01,
  target_kl 0.02); the demonstration gait enters only through the
  motion-prior dataset. Follow the wave discipline of
  `rl_docs/AMP_LOCOMOTION.md` §10/§17: change one or two meaningful
  dimensions per wave, select on videos + tracking/stability metrics.
- Pre-register the gate and both outcomes (if-true / if-false) before
  launch. Coupled bundles are permitted when the mechanism requires
  them; pre-registration and honest verdicts still bind.
- Two aligned-and-budgeted misses in the same behavioral class =
  change the hypothesis or the task spec, not the coefficient.
- Matched-parent controls are mandatory for injected physics/sensor
  axes.

## Reward routing

GLOBAL terms = safety/limits/smoothness only; everything else is
mode-specific. Income must make doing-nothing (parking, freezing,
hovering, refusal) worth less than reasonable progress on the
commanded behavior BY CONSTRUCTION — audit it via the bank, don't
assume it.

## Process

- Launches only via `launch_run.py` (capacity, code-SHA gate, ledger,
  phase gate, `--track joystick|amp`). Ledger edits only via
  `launch_run.py update`. One RL_LOG line per cycle via
  `ops.sh logline`. Clones via `launch_run.py respec`.
- Code changes: cfg-gated, default off, bit-exact when off, tests
  green, `snapshot.sh` before anything trains on them.
- Every analysis ends in a decision that changes the next experiment,
  the reward/eval alignment, the simulator, or the plan. Otherwise
  stop analyzing.
