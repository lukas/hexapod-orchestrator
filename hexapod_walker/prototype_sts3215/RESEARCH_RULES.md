# RESEARCH_RULES — binding agent behavior (operator, 08-21 reset)

How the autonomous loop designs, launches, continues, and interprets
experiments. Startup reading order: `RL_GOALS.md` → `CURRENT_TRUTHS.md` →
`RL_PLAN.md` → the relevant `rl_docs/tracks/<track>/STATUS.md` → this
file + `RUN_INTERPRETATION_RULES.md` before launch/triage.

## Operator orders: obey first, ask after

An operator-authenticated order (KICK session, operator-stamped
feedback, repo ruling) outranks every rule here. Execute it; decline
only for typo-level mistakes, genuine safety violations, unrepairable
failing tests/preflight, or mechanical impossibility — never policy
objections. File conflicts in
`OPERATOR_QUESTIONS.md` (edit it at `.state/OPERATOR_QUESTIONS.md`; the
code-tree path is a read-only symlink) and keep moving; encode
answers back into these docs and close the question.

## Prime directive

The fleet supports the two parallel physical outcomes in `RL_GOALS.md`:
`any_means` delivers smooth joystick walking using any effective method so
physical builds progress now; `rl_only` reaches the same result with walking
learned entirely through RL and no demonstrations anywhere in its lineage.
`tracks.json` maps eight methods to these outcomes. No all-methods-green
requirement applies. Each goal requires a visible interactive joystick sim
demo and video as well as physical evidence; report readiness separately.
A method/simulation PASS is not physical completion. The demonstration-free
training boundary applies to Goal 2 in both sim and hardware.

Every launch or CPU search names its parent outcome, method and the gap it
closes. Keep justified runnable work moving within existing caps, including
practical delivery alongside demonstration-free research. Do not invent filler
runs or reopen closed recipes just because capacity is idle. Use measured
runs and evals for behavioral hypotheses, with tests as specified below.
Do not park lines waiting on the operator: assume-and-go with a recorded
assumption. Only irreducible hands-on robot work and spend approvals may wait;
live camera plus fresh telemetry makes guarded remote robot access runnable
for Robot Lab's serialized runner. Cloud cycles hand physical steps to that
runner and never control the robot directly. The operator may launch
out-of-scope runs; triage them honestly, but agent follow-ups go only to
registered methods serving these two outcomes.

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

## Reward<->eval alignment — evidence from runs, not a rollout test bank

The MDP_PREFLIGHT bank (`rl_move/tests/test_task_semantics.py`, retired
2026-09-08 by the operator) is GONE and must not come back in any form.
It proved reward preferences by rolling out the simulator on the
PRIMITIVE robot model while every run since 08-24 trains on the MESH
model, it took 25 of the suite's 33 minutes, and 60+ of its 385 tests
were red. A test bank that rebuilds "X out-earns cheat Y by N" from
rollouts is an experiment result, not a unit test.

Alignment evidence now lives where the physics is real:

- Before a reward/task-mechanism launch: run the reward-decomposition
  probe on the parent/clone and the best and worst checkpoints of the
  lineage (`eval_checkpoint` with per-term breakdown), and state in the
  hypothesis which term is expected to move and in which direction.
- After the run: the gate eval + video are the verdict. A cheat seen on
  video is encoded as an EVAL METRIC or GATE (something the run report
  measures on every future checkpoint), and the fix is recorded in the
  run story. Do not encode it as a pytest that rolls out the simulator.
- Reward/eval disagreement re-enters SPECIFICATION as before: compare
  decompositions on parent/clone, best gate checkpoint, high-reward
  failed checkpoint and known cheats, then fix reward, eval, or
  simulator until the ranking matches the gate behavior.

## Tests — what a cycle may add to `rl_move/tests/`

These are binding. A cycle that violates them reverts its own test.

1. **Fast.** Every test finishes in under 5 s on the laptop. Anything
   slower carries `@pytest.mark.slow` AND an operator-approved reason;
   the default loop is `pytest -m "not slow"`. Keep the whole default
   suite under 5 minutes serial.
2. **Mechanics, not measurements.** Tests check code paths: a flag
   defaults off and is bit-exact when off, a term is zero when its
   condition is false, a parser rejects bad input. Tests never pin
   measured reward totals, orderings between rollouts, or tuned
   thresholds — those go in the run story and W&B.
3. **The robot you train.** Anything that builds a sim model sets the
   family explicitly via `monkeypatch.setenv("HEXAPOD_MODEL_SOURCE",
   "mesh")` (or the family under test). Never mutate `os.environ`
   directly; it leaks into other tests and made 49 results
   order-dependent.
4. **Self-contained.** No test depends on a generated artifact
   (motion library, checkpoint zip, rise reference, pulled policy)
   unless the test builds it in a fixture. Anything else fails on every
   fresh checkout and gets deleted.
5. **One home, one name.** Tests live only under `rl_move/tests/` (or
   next to robot code in `linux_control/`), one file per module,
   `test_<module>.py`. No `test_*.py` under `rl_move/scripts/` or
   `rl_move/sim/`; pytest never ran the eight that were there.
6. **Diagnose failures.** `main` stays green. A failing regression test
   requires a diagnosis: fix a code regression, or update the test when
   the intended behavior changes. Age alone is never a reason to delete
   or skip it. Remove tests only when their behavior is intentionally
   retired or their coverage is redundant, and record that reason. When
   a track closes, retire its experiment-specific tests while retaining
   mechanics coverage for code that remains in use.
7. **Cheap to own.** No file over 1 000 lines; a 14 000-line test file
   was the reason the suite could not be parallelised.

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
- `speed` track: optimize measured body speed on the current mesh/50 Hz
  transfer stack, not command magnitude, cadence, joint activity or return.
  Start forward-only and keep a Pareto frontier over speed, six-leg gait,
  falls, slip, direction and body motion. The old primitive/full-profile fast
  runs are evidence only: never warm-start across model families or copy their
  1500/80/5-degree contract to hardware. Assisted speed policies are
  `any_means`; demonstration-free descendants stay in `walkcurr`.
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
