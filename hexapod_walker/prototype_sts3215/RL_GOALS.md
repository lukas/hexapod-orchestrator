# What we are doing, in plain English

We have a real six-legged robot (hexapod, STS3215 servos) sitting in
the operator's house. We are training neural-network controllers for
it in a physics simulator (MuJoCo), on cloud GPUs, with an
autonomous loop of AI agents that design experiments, watch them
train, judge the results honestly, and launch the next one.

**The end goal (operator, 08-10): drive the robot around the room
with a joystick — it stands up, sits down, turns, and walks where
you point, reliably. Then the tricks: stand on four legs, walk on
four legs.** Sim numbers only matter insofar as they get us there.
The campaign KPI is the number of unresolved blockers between
today's robot and the next useful hardware joystick test — not GPU
utilization, not experiment count (operator, 08-10).

## What "good" means (operator's own words)

Distance, stability, reliability. The robot should cover real
ground, stay level, and never fall. A policy that walks 0.6 m every
time beats one that walks 1 m or falls at 50/50. Speed targets are
a means, not the objective. Foot slip is not failure by itself —
the scripted gait that walks the real robot slips visibly (08-09);
slip metrics exist to keep sim honest about the real floor, not as
a ban.

## Where we are (edit rule: capability only — details live elsewhere)

Live rulings + hardware facts: **`CURRENT_TRUTHS.md`** (agents read
that before any history). As of 2026-08-10:

- The REAL robot walks under a scripted gait; that is the bar.
- In sim, the learned gait is real (six legs cycling) but creeps;
  fixing that is an operator contact-pricing calibration waiting on
  a tape-measured hardware walk.
- The sim joystick driving stack is hardened and seed-confirmed;
  turn-in-place passed the gate but commanded yaw is still ignored
  (structural drift — mechanism change queued, price tuning closed).
- Stand-up inside the walking policy is the main unsolved skill —
  every attempt so far games the height reward. Full plan and
  evidence: `rl_docs/RISE.md`. A working fallback exists (stance
  policy rises, scripted blend, walk policy drives — sim-proven).
- The four-leg trick holds perfectly but erodes walking when mixed
  into training — goes to a deploy-time specialist.
- Hardware attempt #2 checkpoint (`cw-dep-vref1-r1`) is validated,
  hardened, and staged on the operator's Mac — waiting on bench time.

## The cast

- **The loop:** a watcher script polls training; each finished run
  triggers an agent "cycle" that evaluates it (with video, not just
  scalars), writes a verdict, and launches the next experiment. Its
  binding rules: `RESEARCH_RULES.md` (prime directive, phases,
  MDP_PREFLIGHT, matched-parent controls); blockers and queue:
  `RL_PLAN.md`.
- **Runs** are named `cw-<line>-<idea>` (e.g. `cw-walk-anchortol5`);
  continuations get `-c1`, `-c2`. Everything is recorded in the
  ledger (`rl_move/orchestrator/experiments.json`) and W&B
  (`l2k2/hexapod-balance`).
- **Compute:** CoreWeave pods; GPU pods train 20–40M-step runs in
  ~20–40 min (MJX), CPU pods handle probes and small runs. Idle pods
  are acceptable — peripheral experiments are not.
- **The operator's backlog** of things to learn: `rl_docs/WISHLIST.md`.
