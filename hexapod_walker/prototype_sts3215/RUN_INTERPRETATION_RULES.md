# RL Run Interpretation Rules (operator, 08-21/08-22 - binding)

The triage checklist and verdict vocabulary for every finished run.
Work the questions in order and record the table's verdict.

## The 08-22 reward/eval agreement ruling (overrides everything below)

Every triage starts with one question: **do reward and eval agree?**
Record reward trend and gate/eval trend as up / flat / down before
proposing the next run.

**If eval is unsatisfactory and flat/down while reward is rising, the
default verdict is MISALIGNED, not UNDERTRAINED.** The optimizer is
probably succeeding at the wrong objective, or the eval is not the
operator's desired behavior. Stop same-recipe seed sweeps and longer
budget as the first response. Audit reward/eval/simulator alignment
first.

The alignment audit compares reward decompositions on at least: the
parent/clone, the best gate checkpoint, a high-reward failed
checkpoint, and obvious bad behaviors (park/freeze/wrong-way/sideways/
drag/sacrifice/overspeed as relevant). Fix whichever part is wrong:
reward, eval, or simulator/contact/servo modeling. Encode the observed
cheat in the mode's `test_task_semantics.py` bank before relaunch.

Continue for more budget only when reward and gate/eval metrics are
improving together, or when video shows qualitatively right immature
behavior and the eval trend is moving. If both reward and eval are
flat/bad at adequate budget, treat it as a stuck signal/mechanism, not
a seed-farming invitation.

A run is a genuine FAIL only when (a) nothing is learning — reward AND
task metrics flat with adequate budget — or (b) a reward already
aligned with the eval (bank PASS) plus adequate budget still does not
move the gate metrics. Two aligned-and-budgeted misses in the same
behavioral class = change the hypothesis or the task specification.

## 0. What is this checkpoint allowed to answer?

Read the ledger `phase` and `assessment_scope` before judging.
A canary checkpoint answers mechanism health (boot, finite learning,
routing, telemetry, an improving learnable signal) — not mature
behavior. An acquisition run is judged at its registered budget.
Immature behavior at a canary/early checkpoint never closes a
behavior, architecture, or reward class.

## 1. Did learning happen?

Check BOTH training return and the pre-registered task metric.

- Neither improves with adequate budget: **FAIL — hypothesis did not
  produce learning.**
- Reward rising but eval flat/down: **MISALIGNED** until proven
  otherwise; audit reward/eval/sim before more same-recipe runs.
- Reward rising and eval rising: may be **UNDERTRAINED**; continuation
  is allowed by the registered rule.

## 2. Reward up, evals/task bad?

If eval is not improving, **MISALIGNED** is the default verdict. The
deliverable is not "try more seeds"; it is a reward/eval/sim audit,
bank row, and relaunch. If eval is improving too, classify as
UNDERTRAINED and continue only under the registered continuation rule.

## 3. Does the video look physically correct? (behavioral phases)

An exploit on video (flag-leg, tripod, dragging, freeze, park,
paddle-creep, overspeed attractor) with rising reward = MISALIGNED:
name it bluntly, encode it in the semantics bank, realign, relaunch.
Video overrides scalar success; a checkpoint that scores well but
looks wrong means the metric (or reward) is the bug.

## 4. Eval good but video bad?

**EVALUATOR LOOPHOLE** — fix the evaluator; conclusions that depended
on it are void until re-evaluated.

## 5. Did it beat the frozen parent under the SAME conditions?

For any injected physics/sensor axis, evaluate child AND parent with
identical injection, seeds, horizon, evaluator
(`eval_checkpoint.py --baseline <parent.zip>`). Otherwise no causal
claim.

## 6. Did protected skills survive?

New skill up + protected skill down = **SKILL INTERFERENCE**, not a
clean pass. Guard the current track baselines.

## 7. When is more training justified?

- Reward and eval both rising: yes, per the registered continuation
  rule.
- Reward rising while eval flat/down: no same-recipe continuation by
  default; align first, then continue/relaunch.
- Reward flat AND behavior wrong: no — change the mechanism or spec.

## Classification table

| Training reward | Evals/task | Video | Verdict |
|---|---|---|---|
| flat | flat/bad | wrong | FAIL — hypothesis failed |
| rising | flat/down bad | any | MISALIGNED — audit reward/eval/sim before more budget/seeds |
| rising | improving but bad | right behavior, immature | UNDERTRAINED — continue |
| rising | bad | exploit / stable wrong | MISALIGNED — realign reward with eval, relaunch/continue |
| up | up | wrong | evaluator loophole — fix the eval |
| up | up | good, protected skill down | skill interference |
| up | up | good | PASS / harden |

## Order of evidence

1. Correct physical behavior (video)
2. Held-out gate metrics
3. Protected-skill retention
4. Training task metric
5. Training reward

Reward is never sufficient evidence of success by itself — but rising
reward with flat/down bad evals is the loudest evidence to stop and
audit objective alignment before spending more training budget.
