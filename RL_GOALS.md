# Two goals: smooth joystick walking in sim and on the physical robot

Lukas clarified these goals on 2026-09-08 and expanded Goal 2 on 2026-09-13.
For each goal, he wants to see smooth joystick walking **both in simulation
and on the physical robot**. Goal 2 additionally requires clean RL
rise/hold/lower capability rather than a walk-only handoff.
Each needs a visible, runnable sim demo as well as physical evidence.
They run in parallel so hard RL research does not hold up useful walking
or progress on physical
builds. This file is canonical for purpose and priorities;
`CURRENT_TRUTHS.md` records evidence and `RL_PLAN.md` describes the work.

## OPERATOR PRIORITY (2026-09-21, Lukas): reality-mimicking domain randomization is the path to real-world walking

The single most important thing toward the PHYSICAL walking outcome right now is
a bigger, better domain-randomization range that actually mimics reality, trained
with an ADAPTIVE recurrent (GRU) policy that can infer and adapt to the robot and
environment online. Sim-only method tracks are largely closed/parked; the blocker
to real-world walking is the sim-to-real gap. Cross it by (a) making the twin's
center realistic and (b) randomizing widely enough that the real robot lands
INSIDE the training distribution, then letting a memory-based policy adapt within
it. Weight cluster/agent effort here over re-auditing closed sim-only tracks.

Prioritize, in order:
1. DR ranges that BRACKET the MEASURED reality gap (not arbitrary spreads):
   actuator command latency (real effective ~250 ms; twin base now ~125 ms after
   the sim reality-gap refit merged to main), joint speed ceiling, contact
   friction incl. asymmetric/yaw-slip (real veers ~10 deg/leg), contact stiffness
   (real body-rock ~2x sim), mass (~3 kg battery-out), backlash/link-length.
   Measured values: `hexapod_walker/prototype_sts3215/rl_move/sim/REALITY_GAP_REFIT.md`.
2. An ADAPTIVE recurrent (GRU) policy over that range. A stateless MLP cannot
   infer the current dynamics online; a memory policy does implicit sysid.
3. A STAGED curriculum: learn to walk in an EASY (little/no DR) env first, then
   ramp difficulty across warm-started runs. Do NOT start at full width (that
   stalled cw-walk50hz-drgap/drgap2). In flight: cw-walk50hz-gru-easy-s0.
4. A DR-APPROPRIATE success metric: ROBUSTNESS across the DR range (gait_valid/
   speed HOLDING as randomization widens, eval-swept), NOT clean-sim reward —
   flat by design under wide DR. Do NOT seed-prune wide-DR runs for clean-reward
   stagnation (that false-killed drgap/drgap2).

This serves both goals' PHYSICAL half; it does not change the demonstration
boundary for `rl_only`.

## Goal 1 — working walking by any effective means (`any_means`)

Make the simulated and real robot pleasant and reliable to drive. Use whatever
works: a programmed gait, controller/CPG search, demonstrations, behavior
cloning (BC), adversarial motion priors (AMP), RL, or a combination. A
scripted controller is a valid result; a learned controller is welcome
when it helps. Explicit stand/walk/lower states and controller composition
are also valid.

Use this path to exercise and improve the physical builds: observe walking,
measure limitations, improve the mechanics, calibration, controls or sim,
and repeat. Do not wait for demonstration-free RL, a monolithic policy,
or every research method to succeed before delivering useful walking.

## Goal 2 — full gait learned entirely through RL, no demonstrations (`rl_only`)

Reach the same sim and physical joystick-walking outcome, including reliable
rise, hold and lower, with every motion-producing role learned entirely through
RL. **No demonstrations at any point in any qualifying role's training
lineage**, including programmed-gait demonstrations. Random actor weights alone
do not establish this: a random actor trained against a BC teacher or AMP
motion library is demonstration-assisted.

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
be imported into Goal 2. One monolithic sit/rise/walk/lower actor is not
required: separately trained clean RL roles may be composed with an ordinary
state machine. The composition may choose and blend roles, but it may not
generate motion from a scripted pose path, gait clock, teacher, assisted
policy, or demonstrated controller. Full-direction walking and clean RL
rise/hold/lower are required capabilities, not optional extensions.

## What counts as success for either goal

Each goal has **two required deliverables**, reported separately:

| Goal | Simulation deliverable | Physical deliverable |
|------|------------------------|----------------------|
| `any_means` | Smooth joystick demo using any effective controller/training method | Smooth joystick walking on the real build |
| `rl_only` | Grounded start -> clean RL rise/hold -> full-direction joystick gait -> clean RL lower, with verified demonstration-free lineage for every motion role | The same full clean-RL sequence on the real build |

**Simulation:** provide a named controller/checkpoint, a reproducible launch
command or viewer link, and a viewable video. Lukas must be able to steer it
interactively, not only watch an autonomous fixed-forward rollout. Show the
requested direction/speed/yaw in the viewer/video and demonstrate command
changes, turns, starts, stops and restarts. Preserve the actual run's model,
physics, control rate, observations and controller configuration; include a
full-mesh MuJoCo demonstration under the intended robot conditions. Verify
the active controller, policy identity and model/config in the viewer: the
web runtime can fall back to a scripted gait when it rejects a checkpoint.
Such a fallback cannot represent the `rl_only` demo. Label
easy-physics acquisition and legacy-model previews explicitly; they do not
replace this sim deliverable. Use the existing `sim_viewer/README.md` workflow
and `ops.sh drivevideo` for supported learned walk-checkpoint videos. Where
a policy is not yet supported faithfully in the interactive viewer, report
that integration gap
and show its correctly configured video as partial progress.

For `rl_only`, the acceptance sequence starts grounded, rises and holds under
a clean RL role, walks the full joystick envelope, then lowers under a clean RL
role. The gait panel must include forward, both diagonals, both laterals, both
rear diagonals, reverse, both yaw signs, speed changes, stops and restarts at
the deployable 50 Hz control rate. Every sustained command must retain
six-leg lift/place participation with no parked, dragged or sacrificed leg.
A restricted forward/near-forward envelope, a walk-only policy, or a demo that
omits known failing headings is partial evidence, not Goal 2 completion.

**Physical:** record the actual robot with the controller and build version
identified. A sim demo can complete the simulation deliverable while physical
validation remains open. Physical walking likewise does not remove the need
to show the sim demo. An exported policy or method PASS without the required
demo/evidence does not complete either whole goal.

Before a bounded physical trial, register the command range, duration and
acceptance criteria appropriate to the build. Test requested direction and
speed changes, turning, starts, stops and restarts. Record synchronized
video, commanded versus achieved motion, and robot telemetry. Judge smooth
motion and transitions, feet that lift and place, all six legs participating,
no dragged or sacrificed legs, and no falls. Report any remaining limits on
the usable joystick envelope. Apply the same visible walking-quality and
command-following criteria to the sim demo. Goal 2 requires the clean
training-lineage evidence for both deliverables. Joystick command sequences
used to evaluate a policy are allowed; they do not provide a training gait
demonstration. Existing method gates keep their numerical thresholds.
Report sim and physical readiness independently;
make each available demo visible as soon as it is ready, without waiting for
the other goal or for physical completion.

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
| `walkcurr` | `rl_only` | Discover the full joystick gait and rise/hold/lower through prior-free RL |

Work on both goals within existing compute, spending and safety limits.
Select experiments and engineering work by the gap they close in an outcome;
there is no requirement to turn every method green. Goal 1's physical work
need not wait for Goal 2's easy-sim or real-physics acquisition. This
clarification does not change caps, rewrite past verdicts, reopen closed
recipes, or authorize filler runs. It does reopen the `walkcurr` outcome gap:
the existing forward walk bundle remains useful partial evidence but is not a
completed Goal 2 result. Preserve the fifteen closed off-axis mechanism classes
as evidence; further work needs a genuinely new structural mechanism rather
than another dose or seed of a refuted recipe. Preserve run evidence and use
the current ledger and track journals to choose the next justified work.
