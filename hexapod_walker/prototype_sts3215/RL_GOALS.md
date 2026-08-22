# What we are doing, in plain English

We are training controllers for a hexapod robot in simulation, using
cloud RL runs plus an autonomous experiment loop. As of 2026-08-21 the
loop has exactly two goals and works until both are achieved.

## Goal 1 — joystick control grown from the simple gait

We already have a simple programmed walking gait that works. Use RL,
starting from that gait, to make the robot genuinely joystick
controllable: point the stick, the robot goes there. Done means: in
simulation it follows changing joystick commands for 60 straight
seconds without falling, actually goes where pointed, and slips no
more than the programmed gait does.

## Goal 2 — modern RL from scratch (AMP)

Build the full modern learned-locomotion pipeline described in
`rl_docs/AMP_LOCOMOTION.md`: a policy trained from scratch with
adversarial motion priors (the programmed gait is training DATA, not
the controller), massively parallel PPO, a privileged critic,
observation history, and actuator/fault randomization. Done means the
policy walks beautifully under joystick command, survives pushes,
tolerates broken joints, and transfers unchanged into plain MuJoCo.
We are not using Isaac Lab; the existing GPU simulation stack gets
extended instead. The loop builds whatever tools this needs and does
not wait for the operator.

## What good means

The video is the judge: smooth alternating-tripod walking, feet that
lift and place, no dragged or sacrificed legs, no falls. Metrics
exist to keep the sim honest. And one standing rule: if a run ends
with bad evals but the reward was still climbing, that run is not a
failure — it either needed to run longer or the reward needed to be
brought in line with the evals.

## Process, briefly

A watcher notices finished runs and spawns agent cycles that triage,
record verdicts, and launch the next work toward the two goals. While
either goal is unmet, an idle fleet is a bug, not a rest state. Only
the operator touches the physical robot or starts work outside these
two goals.

Primary docs: `CURRENT_TRUTHS.md` (facts), `RL_PLAN.md` (plan),
`STATUS.md` (dashboard), `RESEARCH_RULES.md` +
`RUN_INTERPRETATION_RULES.md` (rules), `rl_docs/AMP_LOCOMOTION.md`
(goal 2 charter).
