# RL Run Interpretation Rules (operator, 08-10 — binding)

Use this before any deep analysis. This is the triage checklist and
verdict vocabulary for every finished run: work the 8 questions in
order, stop at the first one that fails, and record the table's
verdict — the point is to NOT waste an analysis cycle (or a
continuation budget) on a run the first failing question already
classifies. Complements `RESEARCH_RULES.md` "Judging runs" (known-
exploit one-line STOP, matched-parent control, impossibility kills).

## 1. Did learning happen?
- Check BOTH training return and the pre-registered task metric.
- If neither improves meaningfully: **FAIL — hypothesis did not produce learning.**
- Do not assume “needs more steps” unless correct behavior has already appeared or there is a clear positive trend.

## 2. Did the real task improve, not just reward?
- Reward up + task metric flat/worse: **REWARD / SPECIFICATION BUG.**
- Assume the policy found a shortcut until proven otherwise.

## 3. Did held-out evaluation improve?
- Training task improves + held-out eval flat/down: **GENERALIZATION FAILURE.**
- Possible causes: overfitting, train/eval distribution mismatch, curriculum mismatch, or variance.
- Do not call it a pass.

## 4. Does the video look physically correct?
- Metrics improve + video shows flag-leg, tripod, dragging, jitter, freeze, march-in-place, or another known exploit:
  **EVAL / REWARD BUG.**
- Video overrides scalar success.

## 5. Did it beat the frozen parent under the SAME conditions?
- For noise / DR / friction / latency / actuator injections, evaluate child AND parent with identical:
  - injection
  - seeds
  - horizon
  - evaluator
- Otherwise no causal claim is valid.

## 6. Did protected skills survive?
- New skill improves + old skill regresses: **SKILL INTERFERENCE.**
- This is not a clean pass.

## 7. What happened over training?
Inspect early / middle / final checkpoints.
- Never correct -> mechanism likely wrong.
- Correct behavior appears then disappears -> interference / optimization drift.
- Correct behavior exists and keeps improving -> continuation may be justified.

## 8. When is more training justified?
Continue ONLY when:
- qualitatively correct behavior already exists, AND
- task/eval metrics are still improving or clearly budget-limited.

Never continue because:
- reward is flat,
- behavior is wrong,
- known exploit dominates,
- “maybe another 20M steps will fix it.”

## Classification Table

| Training | Held-out eval | Video | Verdict |
|---|---|---|---|
| flat | flat | wrong | FAIL — hypothesis failed |
| reward up, task flat | flat | wrong | reward/spec bug |
| task up | flat/down | maybe good | generalization failure |
| up | up | wrong | evaluator/reward loophole |
| up | up | good, old skill down | skill interference |
| up | up | good | PASS / harden |
| up | up | good in sim, worse on hardware anchor | sim/transfer failure |

## Default order of evidence
1. Correct physical behavior
2. Held-out task success
3. Protected-skill retention
4. Training task metric
5. Training reward

Reward is never enough by itself.
