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

## Prime directive

The fleet pursues the registered track gates in
`rl_move/orchestrator/tracks.json` and does not stop until all are
green. Every launch or CPU search answers: which gap between the
current state and this track's DONE gate does this work close? Idle
capacity next to an unmet gate is the failure state; there is almost
always a tool to build, an alignment bank to write, a continuation to
fund, or the next milestone arm to queue. Do not park lines waiting on
the operator: assume-and-go with a recorded assumption. Only irreducible
hands-on robot work and spend approvals may wait; live camera plus fresh
telemetry makes guarded remote robot access runnable. The operator may
launch out-of-scope runs; triage them honestly, but agent follow-ups
go only to registered tracks.

## Interpretation (operator, 08-21/08-22 - full text in
RUN_INTERPRETATION_RULES.md)

Every verdict first checks reward/eval agreement. If reward rises but
the gate/eval is unsatisfactory and flat/down, presume reward/eval/sim
misalignment and audit that objective before same-recipe seeds or
longer budget. If reward and eval both improve, a continuation may be
UNDERTRAINED. If both reward and eval are flat/bad, the signal or
mechanism is stuck. Video outranks scalars in both directions:
exploits mean misalignment, and a good-scoring bad-looking checkpoint
means the metric, reward, or simulator is the bug.

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
reward is fixed. Reward/eval disagreement discovered after a run
re-enters this SPECIFICATION step: compare reward decompositions on the
parent/clone, best eval checkpoint, high-reward failed checkpoint, and
known cheats, then fix reward, eval, or simulator until the scalar
ranking matches the gate behavior. This is the mechanism that makes
rising reward meaningful evidence.

## Designing runs

- `joystick` track: warm-start by default (phase clone / walk
  champion lineage); ent 0.001, inherited std, `--asym-critic`.
- `amp` track: from scratch by design (std 1.0, ent 0.005–0.01,
  target_kl 0.02); the demonstration gait enters only through the
  motion-prior dataset. Follow the wave discipline of
  `rl_docs/AMP_LOCOMOTION.md` §10/§17: change one or two meaningful
  dimensions per wave, select on videos + tracking/stability metrics.
- `cpg` track: do not convert the Berkeley-style result into PPO seed
  sweeps. Use `rl_move.sim.paper_cpg_search` and direct behavioral
  scoring over low-dimensional gait parameters. Any teacher or
  motion-library adoption is a measured A/B fork; no silent swap.
- Pre-register the gate and both outcomes (if-true / if-false) before
  launch. Coupled bundles are permitted when the mechanism requires
  them; pre-registration and honest verdicts still bind.
- Grid questions launch as BATCHES (operator 08-22): seed pass-rate,
  dose sweeps, style-vs-control pairs go out in one cycle up to
  `max_new_launches_per_cycle` and free capacity — runs finish in
  minutes, so one-arm-per-cycle serialization wastes hours per
  answer. Batching never excuses filler: each arm carries its own
  hypothesis + gate, and an idle pod next to an EMPTY queue is fine
  (do not invent runs).
- Two aligned-and-budgeted misses in the same behavioral class =
  change the hypothesis or the task spec, not the coefficient.
- Matched-parent controls are mandatory for injected physics/sensor
  axes.
- **Any manual `eval_yaw`/`eval_checkpoint` invocation you hand-write
  (not `ops.sh`, not a harness that already bakes it in) MUST include
  the checkpoint's own training `bus.write_speed`/`write_acc`/
  `bus.servo_vel_max_counts_s=write_speed`/`safety.max_delta_q_deg`
  cfg-sets.** Omitting them silently falls back to the gentle default
  profile (write_speed=400/write_acc=20, ~4x slower slew), which reads
  as a DIFFERENT, incomparable dynamics regime — not a small noise
  band. Caught twice now (joystick stotight45 second-seed re-eval,
  08-22; amp turnpush1-style05-acq1-r2 eval_yaw, 08-23 — the second
  case produced a false PASS that had to be retracted after the
  correctly-configured re-read showed the run was actually badly
  turn-eroded, worse than the park fingerprint). `eval_amp_m5.py` and
  the standard prestage gate always set this correctly; only ad hoc
  hand-run commands are at risk — when in doubt, copy the checkpoint's
  own `command` field's `--cfg-set bus.*`/`safety.max_delta_q_deg`
  args verbatim rather than reconstructing them from memory.

## Reward routing

GLOBAL terms = safety/limits/smoothness only; everything else is
mode-specific. Income must make doing-nothing (parking, freezing,
hovering, refusal) worth less than reasonable progress on the
commanded behavior BY CONSTRUCTION — audit it via the bank, don't
assume it.

## Process

- W&B/GPU launches only via `launch_run.py` (capacity, code-SHA gate,
  ledger, phase gate, `--track <registered-track>`). CPG CPU searches
  run through `rl_move.sim.paper_cpg_search` with JSON artifacts and
  must still be snapshotted, logged, and summarized in the `cpg`
  track doc. Ledger edits only via `launch_run.py update`. One RL_LOG
  line per cycle via `ops.sh logline`. Clones via
  `launch_run.py respec`.
- Code changes: cfg-gated, default off, bit-exact when off, tests
  green, `snapshot.sh` before anything trains on them.
- Every analysis ends in a decision that changes the next experiment,
  the reward/eval alignment, the simulator, or the plan. Otherwise
  stop analyzing.
