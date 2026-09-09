# Two goals: smooth joystick walking on the physical robot

Lukas clarified these goals on 2026-09-08. Both end with the physical
hexapod walking smoothly under joystick control. They run in parallel so
hard RL research does not hold up useful walking or progress on physical
builds. This file is canonical for purpose and priorities;
`CURRENT_TRUTHS.md` records evidence and `RL_PLAN.md` describes the work.

## Goal 1 — working walking by any effective means (`any_means`)

Make the real robot pleasant and reliable to drive now. Use whatever
works: a programmed gait, controller/CPG search, demonstrations, behavior
cloning (BC), adversarial motion priors (AMP), RL, or a combination. A
scripted controller is a valid result; a learned controller is welcome
when it helps. Explicit stand/walk/lower states and controller composition
are also valid.

Use this path to exercise and improve the physical builds: observe walking,
measure limitations, improve the mechanics, calibration, controls or sim,
and repeat. Do not wait for demonstration-free RL, a monolithic policy,
or every research method to succeed before delivering useful walking.

## Goal 2 — walking learned entirely through RL, no demonstrations (`rl_only`)

Reach the same physical joystick-walking outcome with a walking policy
learned entirely through RL. **No demonstrations at any point in its
training lineage**, including programmed-gait demonstrations. Random actor
weights alone do not establish this: a random actor trained against a BC
teacher or AMP motion library is demonstration-assisted.

- No BC initialization or anchor, imitation/AMP reward, demonstration
  replay, teacher action targets, or distillation from an assisted policy.
- Fading a teacher, imitation loss, or scripted gait residual to zero later
  does not erase that assistance from the policy's training history.
- Start a clean RL lineage; continuing a checkpoint from a verified clean,
  demonstration-free RL lineage is allowed. Record initialization,
  checkpoint ancestry, training inputs, rewards, and action/controller paths.
- Simulator calibration, system identification, task rewards, curricula,
  domain randomization, and ordinary safety/control plumbing are allowed.
  They must not conceal a gait teacher or a scripted walking controller.
  The existing `walkcurr` method retains its stricter no-gait-clock,
  no-BC-teacher, no-motion-prior contract.

Goal 1's robot measurements and tools can improve Goal 2's simulator and
validation. Its demonstration-trained weights and gait supervision cannot
be imported into Goal 2. A single sit/rise/walk/lower actor and fault recovery
are possible extensions, not additional parent goals or prerequisites for
joystick walking.

## What counts as success for either goal

The evidence must come from the **physical robot**, with the controller and
build version identified. Simulation passes, an exported policy, an easy-
physics discovery, and a packaged demo are useful milestones; none alone
establishes either parent goal.

Before a bounded physical trial, register the command range, duration and
acceptance criteria appropriate to the build. Test requested direction and
speed changes, turning, starts, stops and restarts. Record synchronized
video, commanded versus achieved motion, and robot telemetry. Judge smooth
motion and transitions, feet that lift and place, all six legs participating,
no dragged or sacrificed legs, and no falls. Report any remaining limits on
the usable joystick envelope. Goal 2 also requires the clean training-lineage
evidence above. Existing method gates keep their numerical thresholds.

Robot experiments use the existing observation, telemetry and abort rules.
Cloud RL cycles hand physical work to Robot Lab's serialized guarded runner;
they do not control the robot directly. Routine observed hardware work is
runnable under standing authority; only a concrete hands-on need requires
Lukas to intervene.

## Methods supporting the two goals

`rl_move/orchestrator/tracks.json` keeps the seven stable method IDs. Its
`parent_goal` field maps each method to an outcome; a method's DONE/PASS is
only its own milestone, not parent-goal completion.

| Method track | Parent goal | Role |
|-------------|-------------|------|
| `joystick` | `any_means` | Improve joystick walking from a scripted gait or teacher |
| `amp` | `any_means` | Learn using demonstration-based motion priors |
| `cpg` | `any_means` | Search programmed gait/controller parameters directly |
| `standwalk` | `any_means` | Explore one learned sit/rise/walk/lower policy |
| `assistfade` | `any_means` | Learn with assistance, then reduce it |
| `todaypolicy` | `any_means` | Deliver usable controllers/bundles and physical handoffs |
| `walkcurr` | `rl_only` | Discover walking through prior-free RL |

Work on both goals within existing compute, spending and safety limits.
Select experiments and engineering work by the gap they close in an outcome;
there is no requirement to turn every method green. Goal 1's physical work
need not wait for Goal 2's easy-sim or real-physics acquisition. This
clarification does not change caps, rewrite past verdicts, reopen closed
recipes, or authorize filler runs. Preserve run evidence and use the current
ledger and track journals to choose the next justified work.
