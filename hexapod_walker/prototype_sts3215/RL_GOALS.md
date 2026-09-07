# What we are doing, in plain English

We are training controllers for a hexapod robot in simulation, using
cloud RL runs plus an autonomous experiment loop. The binding list is
`rl_move/orchestrator/tracks.json`; as of 2026-08-30 there are six
registered tracks.

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

## Goal 3 — CPG/controller search

Search a low-dimensional gait/controller space directly in MuJoCo as
a pragmatic non-PPO path. Done means the saved controller handles
walking, turning, stopping, and restarts with zero falls and low slip;
any use as a teacher is tested as an A/B fork.

## Goal 4 — prior-free walking

Find out whether PPO from a random policy can discover a clean hexapod
walk without a gait clock, BC teacher, or motion prior. Done means a
prior-free policy passes a held-out contextual walking panel with
six-leg gait validity, direction following, low slip, and no falls.

## Goal 5 — one useful stand/walk policy

Train a mesh/100 Hz policy that can do the whole job by itself: sit,
rise, follow joystick commands, and lower. This is the hard research
lane, and it continues even if a composed controller works first.

## Goal 6 — a working policy bundle today

Produce something useful to drive in MuJoCo now and transfer toward the
robot later. This track may compose explicit policy+state pieces:
tuck stand, RL walk, lower, CPG or scripted fallback, exported policy
JSON, browser/controller selectors, and a transfer manifest. It is a
delivery track; it does not declare the single-policy problem solved.

## What good means

The video is the judge: smooth alternating-tripod walking, feet that
lift and place, no dragged or sacrificed legs, no falls. Metrics
exist to keep the sim honest. And one standing rule: if a run ends
with bad evals but the reward was still climbing, that run is not a
failure — it either needed to run longer or the reward needed to be
brought in line with the evals.

## Process, briefly

A watcher notices finished runs and spawns agent cycles that triage,
record verdicts, and launch the next work toward the registered
tracks. While any track is unmet and runnable work exists, an idle
fleet is a bug, not a rest state. Guarded agents may operate the physical
robot remotely within the active campaign using live camera, fresh telemetry,
and an abort path. The operator owns hands-on manipulation and decisions that
expand work outside the registered tracks.

Primary docs: `CURRENT_TRUTHS.md` (facts), `RL_PLAN.md` (plan),
`STATUS.md` (dashboard), `RESEARCH_RULES.md` +
`RUN_INTERPRETATION_RULES.md` (rules), `rl_docs/AMP_LOCOMOTION.md`
(goal 2 charter).
