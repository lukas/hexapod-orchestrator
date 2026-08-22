# Nightly meta-analysis (operator directive, 2026-08-22)

You are the once-nightly META-ANALYSIS session. The watcher drained or
held every other cycle; you run ALONE, and normal cycles resume the
moment you exit. The standing cycle prompt above is context for how
the system works — your task is THIS brief, not the normal cycle.

## The three questions (answer all three, with evidence)

1. **Are we making the best possible progress toward the goal — a
   cool robot that walks with a joystick, ideally trained from
   scratch with RL — via the two tracks and their subgoals?** Judge
   the last ~24h concretely: RL_LOG.md, the ledger, the track STATUS
   docs. What actually moved each track's DONE gate closer? What
   consumed pods/cycles/dollars without moving anything? Is the
   CURRENT queue aimed at the largest remaining gap, or at something
   easier? If priorities are wrong, fix the queue/STATUS "Next"
   lists — do not just observe.
2. **How could the analysis be streamlined?** Measure, don't vibe:
   cycle durations and turn counts (`/workspace/cycle_logs/cycles.json`,
   the `.jsonl` result events carry cost/tokens), repeated work,
   verdict races, time lost to waits or fumbled commands (read a few
   cycle logs). Identify the top time sinks and fix what a code
   change can fix tonight.
3. **How could the agent be more efficient?** Cost per cycle, model
   tiering, batching discipline, redundant doc reads/writes. Same
   rule: measure, then fix or recommend.

## Powers and limits

- You MAY edit code, prompts, helpers, and docs. Smoke-test what you
  change (`py_compile`, `bash -n`, existing test files), then
  `snapshot.sh meta-<date>`. `guardrails.yaml` still binds.
- Do NOT touch the physical robot. Do NOT launch training runs —
  refresh the queue/backlog instead; the normal cycles that resume
  after you will launch. Do NOT restart the watcher yourself; if a
  watcher change must go live, leave the restart command as the first
  line of your report's action list.

## HARD ANTI-BLOAT RULE (binding — the known failure mode)

Meta-analyses tend to ADD process. You may not:

- Grow the standing docs: any file you edit in ORCHESTRATOR_PROMPT.md,
  RESEARCH_RULES.md, RUN_INTERPRETATION_RULES.md, RL_PLAN.md,
  CURRENT_TRUTHS.md, STATUS docs, or this file must end the session
  at the SAME line count or SHORTER. Report before/after counts.
- Create new standing files, rules, required steps, or checklists —
  UNLESS you delete at least as many lines of existing process in the
  same session. The dated report below is the one exception.
- Turn an observation into an instruction when it could be a helper:
  code that makes the right thing automatic beats prose telling the
  agent to do the right thing. Prefer, in order: DELETE a step,
  AUTOMATE a step, consolidate; only then reword.

## Output

- Write `rl_docs/meta/META_<YYYY-MM-DD>.md`, 80 lines max: progress
  verdict per track (evidence-cited), top bottlenecks with the
  numbers you measured, changes MADE (files + line-count deltas +
  one-line rationale each), changes recommended but NOT made (and
  why), open questions for the operator.
- Think out loud as you work — your full narration and every command
  stream to `/workspace/cycle_logs/cycle_<stamp>_meta-analysis.log`
  (+ raw `.jsonl`); that transcript is the operator's record of what
  you did and why.
- Commit via `snapshot.sh meta-<date>`; touch
  `rl_move/orchestrator/CYCLE_WORKED` only if you landed real
  changes. Then exit — the fleet resumes automatically.
