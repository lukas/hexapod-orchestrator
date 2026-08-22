# RL Run Interpretation Rules (operator, 08-21 — binding)

The triage checklist and verdict vocabulary for every finished run.
Work the questions in order and record the table's verdict.

## The 08-21 ruling (overrides everything below on conflict)

**If a run stops (budget end, canary, kill) with bad evals but
training reward still rising, that is NOT a fail.** It means one or
both of:

1. **UNDERTRAINED** — the run needs to go longer. Continue from the
   last checkpoint.
2. **MISALIGNED** — the reward is not aligned with the evals: the
   policy is honestly maximizing what we priced, and what we priced is
   not the gate behavior. Fix the reward so its optimum is the gate
   behavior (encode the observed cheat in the mode's
   `test_task_semantics.py` bank first), then relaunch or continue.

Choosing between them: if the video shows qualitatively right behavior
still improving, continue. If the video shows an exploit or a stable
wrong behavior earning rising reward, realign first — more steps buy
more of the same exploit. When genuinely unsure, do both as a pair
(continuation + realigned arm) and let the evidence decide.

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
- Reward rising: apply the 08-21 ruling — this run is not a FAIL,
  classify it UNDERTRAINED or MISALIGNED and act accordingly.

## 2. Reward up, evals/task bad?

**MISALIGNED and/or UNDERTRAINED (08-21 ruling)** — never a terminal
verdict. The deliverable of this triage is a concrete next action:
the continuation launch, or the reward change + bank row + relaunch.

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

- Reward rising: yes, per the 08-21 ruling — unless the video shows a
  reward-earning exploit, in which case align first, then continue.
- Reward flat AND behavior wrong: no — change the mechanism or spec.

## Classification table

| Training reward | Evals/task | Video | Verdict |
|---|---|---|---|
| flat | flat/bad | wrong | FAIL — hypothesis failed |
| rising | bad | right behavior, immature | UNDERTRAINED — continue |
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
reward with bad evals is always evidence the run deserves alignment
work or more budget, not a burial.
