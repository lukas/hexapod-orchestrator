# What we are doing, in plain English

We are training controllers for a real STS3215-servo hexapod in MuJoCo,
using cloud RL runs plus an autonomous experiment loop.

## Goal

Drive the physical robot with a joystick: stand up, sit down, turn, and walk
where pointed, reliably and repeatedly. After that, work on the party tricks:
stand on four legs and walk on four legs.

## What Good Means

Distance, stability, reliability. A policy that moves less but never falls is
better than a faster policy that falls half the time. Speed and slip metrics
are tools, not the objective. Foot slip is not automatic failure because the
scripted real gait slips visibly while still being useful.

## Current State

Read `STATUS.md` for the live dashboard and `rl_docs/DOWNLOAD_ANSWER.md` for
what would be downloaded today. The current baseline is a hierarchy:

- stance: `footlow2_hard1`
- walk: `bcgait1_hard1`
- session controller: re-anchor, entry slew, STOP->stance hold, rot60 wrapper

The robot is temporarily off the bench for repair, so the active sprint is
sim-only reliability for rise + walk. Open decisions are post-lower rise
promotion, fast-gait continuation after live canaries finish, and bench
promotion once the robot returns.

## Process

The watcher notices finished runs, spawns an agent cycle, records verdicts,
and launches only work that can change the next useful robot test or the
current download answer. Idle GPUs are acceptable; peripheral experiments are
not.

Primary docs:

- `CURRENT_TRUTHS.md` - accepted facts and rulings
- `RL_PLAN.md` - current operating plan
- `STATUS.md` - live dashboard
- `RESEARCH_RULES.md` - launch/triage rules
- `rl_docs/DOWNLOAD_ANSWER.md` - download candidate and evidence
