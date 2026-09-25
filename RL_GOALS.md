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

## DEPLOY CONTRACT note (2026-09-22 21:49) WAS STALE — CORRECTED same day (2026-09-22, refill cycle)
The note below this one claimed the robot runtime accepts only
`meta.architecture in {mlp, dual_gru}` and REJECTS single-GRU/obs-74
("unsupported meta.architecture gru"), and that a GRU-first physical
trial was therefore BLOCKED. That was already false when written: path
(b) it names as a fallback — "extend np_policy+exporter with a
single-GRU (gru/obs-74) arch" — was built and tested the PREVIOUS day
(2026-09-21 ~22:2x, standwalk track; see `CURRENT_TRUTHS.md`'s own
2026-09-21 CORRECTION entry, which this later note failed to check).
`rl_move/np_policy.py` has had `ARCH_SINGLE_GRU = "gru"` since then —
`meta.architecture="gru"` is explicitly accepted, not rejected — and
`rl_move/deployed_policy.py::WALK_OBS_DIMS = (72, 74, 75, 81, 93)`
lists obs-74 as a supported walk contract `linux_control/rl_policy.py`
already documents in its own module docstring. Live-verified this
cycle: `load_np_policy("linux_control/policies/
walk50hz_gru_dr10_frictionasym_stickslip_dose08.json")` (the exact
single-GRU/obs-74 export `todaypolicy`'s `GO_NOGO.md` already names as
today's TOP physical-trial pick) loads cleanly as a recurrent
`NumpyGruModel`; `test_export_single_gru_is_compact_valid_and_loadable`
and the rest of `rl_move/tests/test_export_policy_np.py` +
`test_np_policy.py` pass (only the two pre-existing order-independent
flakes on record reproduce). **There is no deploy blocker and no
dual-GRU/obs-81 retrain requirement for this candidate.** The MLP
full-envelope candidate remains independently deployable (stateless);
now BOTH architectures the bundle offers are hardware-runnable today.
Do not action the two "paths" below — they solve an already-solved
problem. This correction does not touch the file's other guidance.

## SUPERSEDED — DEPLOY CONTRACT reality (2026-09-22): the single-GRU ladder winners are NOT robot-runnable as-is [FACTUALLY WRONG, see correction above]
Before prioritizing a GRU PHYSICAL trial, know the contract. The robot runtime
(rl_move/np_policy.py + linux_control/rl_policy.py) accepts only
meta.architecture in {mlp, dual_gru}, and dual_gru REQUIRES obs-81 (the frozen
6-mode one-hot hold/rise/lower/walk/turn/quad that gates the two GRU cores).
The wide-DR ladder used `--gru` = a SINGLE GRU -> exports as architecture="gru",
obs-74 -> the runtime REJECTS it ("unsupported meta.architecture gru"). It exports
+ passes recurrent parity for MuJoCo replay only. So a GRU-first physical trial is
BLOCKED until a deployable candidate exists. Two paths: (a) PREFERRED — train the
final wide-DR/friction candidate as the deployable DUAL-GRU + obs-81 contract
(DualGruActorCriticPolicy + the 6-mode one-hot; this same arch also serves the
unified stand/walk/rise/lower line), so it exports straight to the Uno Q; or
(b) extend np_policy+exporter with a single-GRU (gru/obs-74) arch. The MLP
full-envelope candidate (mlp quad5-torque-envwide) IS deployable today (stateless).

## STANDWALK IS NOT CLOSED (2026-09-22, Lukas) — reopen the sim campaign, reality-bracketing axes are UNTESTED

The wide-DR ladder validated dr-1.0 on GRU+MLP, but ONLY under GLOBAL friction.
Do NOT report standwalk/sim closed: three reality-CRITICAL, GPU-LAUNCHABLE levers
are still untested. Warm-start the VALIDATED dr-1.0 GRU `cw-walk50hz-gru-dr10-envwide-s2`
and launch them (fill the idle fleet with these + seed replicas + a gentle dose ramp):
1. PER-FOOT friction ASYMMETRY + STICK-SLIP (in flight: cw-walk50hz-gru-dr10-frictionasym-stickslip-s0):
   `--cfg dr.foot_friction_scale=0.7,1.3 --cfg dr.foot_stickslip_gain=0.0,0.4`.
   This targets the MEASURED gap (real fwd over-progression ~1.6x + veer ~10deg/leg
   the constant-coeff contact cannot model). HIGHEST leverage.
2. IMU DROPOUT/FREEZE + servo DROP-BURSTS (merged to main 305ba04f): `--cfg dr.imu_dropout_prob_max=0.02
   --cfg dr.imu_dropout_ticks=15 --cfg dr.imu_dropout_dead_frac=0.3 --cfg dr.cmd_drop_burst_len=6`.
   A GRU can dead-reckon through these; an MLP cannot.
3. Then the RISE/HOLD/LOWER campaign (see the queued note below).
These are NEW launchable work, NOT a refuted re-dose. A "no launchable lever" refill
verdict is WRONG while any of these is untested — launch them.

## HARDWARE-CONFIRMED #1 LEVER (2026-09-22): the PLANT (stance), NOT friction/DR. Retrain on an EXTENDED plant.
A hexapod2 hardware A/B (lukas-ef, 10 runs) settled it: real body-rock and forward
speed track the STANCE, not the DR recipe. Working walkteach stands EXTENDED
(robot_abs hip 16 / knee ~84, foot ~211 mm) -> 21-28 mm/s, 14-17 dps. EVERY pure-RL
policy stands TUCKED (hip ~16 / knee ~100, foot ~175 mm, feet under the knees) ->
1-9 mm/s, 19-29 dps, at 3-4x the current: it POGOS in place, no traction. The
friction-realism candidates (dose08, combo) rocked the SAME (21-22 dps) and translated
no better -- so FRICTION REALISM AND MAX-WIDE DR ARE NOT THE TRANSFER LEVER (hardware-
refuted). The tucked plant is the sim canonical `robot_abs (20,100)` made canonical
2026-09-02; every post-09-02 pure-RL policy inherited it.

PLUMBING NOW EXISTS (2026-09-22): `mjx_train_setup._env_kwargs` reads cfg
`plant.hip_deg`/`plant.knee_deg` -> `plant_deg=[0,hip,knee]x6` (robot_abs; null default =
tucked 20/100, bit-exact). Launch an extended-plant run with `--cfg plant.hip_deg=20
--cfg plant.knee_deg=82` (foot ~216 mm). On the orchestrator branch (via snapshot); merge
to main so it is explicit everywhere. IN FLIGHT: cw-walk50hz-gru-extplant82-s0 (warm-start
easy-cont, dr 0.3); GATE on the policy OWN settled foot radius >=205 mm, NOT reward.
META-LESSON (why the campaign missed the plant): DR randomized friction/contact-stiff/mass/
latency and STILL passed tucked policies -- because the PLANT IS NEVER RANDOMIZED (every
episode stands at 20/100 and the sim gives it traction). So the sim`s error is NOT a DR-set
parameter; it is the actuator/compliance model or the reward plant anchor (high real current
1.0-1.15 A + rock + no slip = feet GRIP while the body bounces = compliance, not friction).
REWARD COUPLING NUANCE (lukas-ef, 2026-09-22): the WALK reward does NOT pin feet/height
to the plant -- `reward.walk_height_gate` and `reward.walk_anchor_gate` default 0 (config
leaves them there); anchored_stance anchors feet to their OWN touchdown; PLANT_SPEC footprint
tol applies only in the STAND phase. The plant couples to gait via the RESET distribution +
stand-phase spec + the robot`s RL-stand handoff, NOT a reward term. => extplant82 is a
DISCRIMINATOR: (i) settles foot >=205 mm AND walks like walkteach on the floor = plant IS the
lever; (ii) walks in sim but DRIFTS back toward a tuck / still pogos = plant was incidental and
the GAIT/DUTY/SLIP reward gates themselves favour the tucked scrubbing gait (that becomes the
lever, a reward-design fix). Read the result this way.
SIM-REALISM VERDICT (2026-09-22, validated): friction is NOT the lever. Lowering nominal
foot-ground mu 2.0->0.6 degrades ALL policies in PARALLEL (does not separate tucked from
extended); it raises YAW gyro but the real tucked rock is ROLL-DOMINATED (real roll ~14-18 dps
vs sim ~7 at EVERY mu) -- mu leaves the dominant ~2x ROLL deficit untouched. Nominal stick-slip
is a no-op (boost-only). Contact levers (solref/solimp/condim) already recorded NEGATIVE for the
rock (gaitval2, b616). Keep `env.foot_friction_slide=0`. Full: ~/.hexapod/analysis/mu_validation.md.
HIGHER-PROBABILITY sim-realism levers (do these instead): (1) actuator LOADED-params -- the b616
refit (branch claude/sim-refit, UNMERGED) already gave +35% rock; (2) MASS/CoM/INERTIA -- the
robot has NEVER BEEN WEIGHED (sim guesses 3.49 kg; mass scales rock AND current, aliases the
actuator fit); (3) yaw-slip asymmetry. ACTION: WEIGH the robot + measure CoM; then merge/test the
actuator refit against the tucked-fails/extended-works criterion.
Sim-realism fix = make the twin FAIL a tucked stance (validate: existing tucked policies show
~20 dps/~5 mm/s, extended ~15 dps/20+ mm/s). Diagnosis in progress.

PLANT RETRAIN ATTEMPT 1 FAILED but the TEST WAS FLAWED (2026-09-22): both extended-plant
runs (extplant82-s0 warm-start, extplant82-scratch-s0 from-scratch) collapsed (ep_rew -809/-1069,
not walking) -- BUT both had `walk_curriculum=False` and NO BC anchor, at only 14M steps. Every
successful walker used the BC-anchor + walk-curriculum multi-stage pipeline; a naive 14M run at a
NEW plant without them is not a fair test. Do NOT conclude the extended plant is unlearnable.
PROPER test: extended plant (--cfg plant.hip_deg=20 plant.knee_deg=82) WITH the BC anchor + walk
curriculum, ideally WARM-STARTING FROM walkteach (already an extended walker, robot_abs ~20/84),
NOT from a tucked policy or cold from-scratch. Alternative: a PLANT CURRICULUM (start at the
trainable tucked plant, ramp plant.knee_deg 80->62 over training). This needs the orchestrator`s
curriculum/BC stack. Still OPEN whether the tuck is (a) fixable by plant+curriculum or (b) a task
reward-gate local-optimum (gait/duty/slip favour scrubbing) -- both extended runs failing without
the stack does not yet distinguish these.

ACTION (do this before more friction/DR work): retrain the walk policy on an EXTENDED
plant -- robot_abs ~hip 20 / knee ~82, foot ~215 mm (the STEP stance walkteach`s
teacher used) -- or a PLANT BAND spanning tucked->extended so the policy is not locked
to the tuck. Levers: `plant.hip_deg`/`plant.knee_deg` in config.yaml (currently null =>
standing_pose/plant_pose.json; require_captured_plant=true), and the standing_pose /
capture_plant asset that became (20,100) on 09-02. Verify the retrained policy holds
foot radius ~210+ mm in sim (RealLegFK) before hardware. Do NOT burn more GPUs on
friction/DR-widening for the TRANSFER goal until the plant is fixed -- it was the
confound the whole wide-DR campaign missed. (Full data: ~/.hexapod/analysis/
rl_gait_trials.jsonl, lab_runs/20260922-18*.)

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

### OPERATOR DIRECTIVE (2026-09-22, Lukas): keep ALL GPU pods busy every cycle
Idle GPUs are NOT acceptable while the wide-DR priority above is open. This
OVERRIDES any "GPU idle is intentional" default. The staged ladder is sequential
(each rung warm-starts the next), so you MUST PARALLELIZE AROUND it — never let
the fleet sit on a single rung. Every cycle:
- Run `capacity.py` at the START and END. A cycle that ENDS with free slots while
  this priority is open has UNDER-DELIVERED: queue more and `drain` before finishing.
- Fill every FREE slot (`launch_run.py backlog` + `ops.sh drain`) with high-priority
  parallel work toward the wide-DR / GRU-ladder goal, in this order:
  1. SEED REPLICAS (s1,s2,s3) of the current and just-passed ladder rungs —
     robustness across seeds IS the success metric; seed spread is signal.
  2. PER-DR-AXIS ABLATIONS at the live rung (latency / friction / contact-stiff /
     mass / backlash / stick-slip, each alone and each left-out) to find which
     axis breaks first and needs a structural fix, not just a wider spread.
  3. PARALLEL rungs from already-PASSED checkpoints (a finer half-step, or the
     next rung at extra seeds) rather than waiting on one rung serially.
  4. The MLP wide-DR line in parallel with the GRU ladder.
- TARGET: 0 free ready slots whenever this priority is open. ~16 H200 slots are
  available; use them. Canonical GRU DR ladder in flight (2026-09-22): the
  `cw-walk50hz-gru-dr0N-ladder-loadslipcap-s0` chain off the `fromcont` converged
  parent (dr-0.5 191, dr-0.6 179 strong; climbing to dr-1.0). Fan seeds + axis
  ablations of THIS ladder across the free pods.

### NEXT CAMPAIGN (queued 2026-09-22, Lukas): apply the SAME wide-DR + GRU treatment to RISE / HOLD / LOWER
Once the walk DR ladder lands at dr-1.0 and validates, run the SAME proven recipe
on the rise/hold/lower skills (Goal 2 `rl_only` half): converged EASY parent ->
staged wide-DR ladder (0.3->1.0, the loadslipcap + pin5b cap discipline) ->
adaptive GRU. Do NOT detour the walk ladder for this; it is the queued follow-on.
The reward that makes rise/lower CONTROLLED (not a drop) ALREADY EXISTS — do not
reinvent it:
- Rise AND lower TRACK A SLOW HEIGHT-REFERENCE RAMP (rise ~4 s, lower ~5 s — the
  code: "the 5 s descent IS the gentleness constraint"). The Gaussian height
  kernel penalizes deviating from that ramp, so a controlled trajectory beats a
  collapse BY CONSTRUCTION (dropping faster than the ref => height_err => less pay).
- Plus k_rise_progress (potential, per-mm), k_rise_milestone, the curl channel
  (feet-under-body, for the belly-start that has no height change to score), and
  hold_max_height_drop_mm during hold.
To make it LOOK graceful (low jerk, no lurch), turn UP the opt-in smoothness
profile on the rise/lower task (k_gyro 0.15 / k_action_delta 0.03 /
k_action_accel 0.02, attitude_alpha 0.99) — same levers as walking, low by default.
FOLD IN the new failure axes once merged (branch claude/dr-imu-dropout-servo-burst):
a rise/lower that holds when the IMU FREEZES mid-motion or servo writes drop in
BURSTS is a strong GRU robustness target — the memory policy can dead-reckon the
height through a sensor dropout where an MLP cannot.
Current state: rise-from-belly and lower are the HARD, not-yet-solved skills
(config notes belly-start 0/6, lowerheavy FAIL); the reward is sound, the skill
is not nailed. The current DR ladder is WALK-ONLY (goal-mix walk=1.0) — rise/lower
is not being trained yet. This is the follow-on after walking validates at dr-1.0.

### DR EXTENSION (2026-09-22, Lukas): turn on per-foot friction ASYMMETRY + STICK-SLIP
Global ground friction IS already randomized (friction_scale 0.6-1.4x at dr=1.0) +
contact stiffness (0.7-2.0x). But the two reality-CRITICAL friction effects are
default-OFF and should be turned on in the wide-DR ladder:
1. PER-FOOT friction ASYMMETRY -- `foot_friction_scale` defaults (1.0,1.0) = every
   foot identical each episode. Real floors/feet differ foot-to-foot, and
   asymmetric grip is what makes the robot VEER. Enable:
   `--cfg dr.foot_friction_scale=0.7,1.3` (drawn PER-FOOT => asymmetry; optionally
   concentrate per-side via the foot group mask).
2. STICK-SLIP -- `foot_stickslip_gain` defaults (0.0,0.0)=OFF. MuJoCo uses a
   CONSTANT friction coefficient; real rubber feet have static > kinetic (grip,
   then break loose and slide). Enable:
   `--cfg dr.foot_stickslip_gain=0.0,0.4` (with dr.foot_stickslip_vel_ref_mps=0.02).
WHY: the measured reality gap is exactly here -- the refit found real forward
OVER-progression ~1.6x and veer ~10 deg/leg, attributed to slip/veer the rigid
constant-friction contact does NOT model (see REALITY_GAP_REFIT.md). Randomizing
the GLOBAL coefficient +-40% does not capture "one side grips, one side skids
mid-stance." This is also a GRU win: a memory policy can feel a slippery foot from
proprioceptive history and adapt online; an MLP cannot. Fold into the wide-DR
ladder with the usual convention (probability follows the curriculum, ramp gently
on the mature dr-1.0 policy). Consider widening global friction too (e.g. 0.5,1.5).




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


## OPERATOR DIRECTIVE 2026-09-23 — HARD-WORLD DR (uneven ground, off-balance)

Lukas: start really hard WORLD domain randomization. Add training terrain/dynamics DR that
the current envelope lacks:
- UNEVEN GROUND: per-episode height-field / tile bumps / slopes under the feet (not just a
  flat plane), randomized amplitude + spatial scale.
- TILTS: randomized ground plane roll/pitch so stance is off-level.
- PERTURBATIONS: random external pushes / impulses to the chassis mid-stride; randomized
  starting pose off-balance; foot-slip events.
- Keep the existing axes (mass, friction, latency, imu_dropout, cmd_drop) ON TOP of these.

WHY / SCOPE: measured evidence (2026-09-23, ~/.hexapod/analysis/rl_sim2real_gap.md,
contact_model_program.md) shows deployed RL policies walk in sim but SPIN/STALL on hardware,
and the failure axis is OUTSIDE the current DR (friction/imudrop DR did not help). Hard-world
DR is a ROBUSTNESS lever: force policies that do not rely on idealized flat grippy contact, so
they tolerate the real floor's traction they cannot predict. It is COMPLEMENTARY to, not a
substitute for, the separate PRECISION fix (making the nominal foot-ground contact model
match reality — that work is tracked in contact_model_program.md). Do not read this directive
as "the fix was found." Stay within existing compute/spend/safety caps and the ledger; prefer
adding terrain/perturbation DR as new arms over refuted friction-dose recipes.

### ADDENDUM 2026-09-23 (contact sweep result) — add PER-LEG ACTUATOR DR
The contact sweep (~/.hexapod/analysis/contact_sweep_result.md) found the dominant RL sim2real
gap is ACTUATOR EXECUTION, not contact: clean policy sim 653 mm -> real executed joints 290 mm
-> real 169 mm+spin. The feed-forward policy corrects contact asymmetry and ignores IMU latency
in sim; only a degraded actuator changes it. So the highest-value ROBUSTNESS additions are:
- STOCHASTIC PER-LEG ACTUATOR DR: per-leg (asymmetric) servo stiction / backlash / load-lag /
  torque-limited slew, randomized per episode and per leg — NOT the current symmetric velocity cap.
- Keep the uneven-ground / tilt / perturbation terrain DR above; add CONTACT-ASYMMETRY (per-foot
  friction) DR as a secondary axis.
The matching PRECISION (non-DR) lever, tracked separately: fit a stochastic per-leg servo model to
measured cmd-vs-q traces and drive it CLOSED-LOOP so the sim reproduces the stall/spin.


## OPERATOR DIRECTIVE 2026-09-24 — ADAPTIVE WALKER: bigger model + curriculum + wider ASYMMETRIC DR (two tracks)
Goal: a smooth ADAPTIVE real walker. Evidence (~/.hexapod/analysis/, esp. servo_transfer_fit.md + hexapod-rl-sim2real-gap):
deployed RL policies walk in sim but STALL+SPIN on hexapod2. The ONLY physical lever that reproduces it is
PER-LEG ASYMMETRIC geometry/zero error (foot placement): at ~+-4-6% effective per-leg foot displacement the sim
policy also stalls/spins STOCHASTICALLY (matches real mixed-sign spin). Realistic per-leg zero (+-2-3 deg) + link
(+-2%) errors reach that regime; current DR (joint_zero_bias +-1 deg, link_len_leg 1.2%) is TOO SMALL. Also:
training episodes are only 5 s (config episode.seconds) -- too short for a recurrent policy to infer/adapt to its env.
The actuator/contact/friction/torque levers are all refuted (sim AND hardware, incl. the write_speed A/B); the lever
is the LEARNED GAIT + robustness to the robot's own miscalibration. This SUPERSEDES the hip-torque-limit DR framing
(outcome-matching, not physical).

RUN BOTH TRACKS within compute/spend/safety caps + the ledger:

TRACK A -- new BIGGER recurrent model, curriculum from scratch:
- Recurrent capacity up: single-GRU hidden 128 -> 256-384 (memory for online env inference). Deployable via the gru runtime.
- CURRICULUM (REQUIRED -- cold max DR will not learn): ramp easy->hard over training -- DR magnitude, episode length
  (5 s -> 20-30 s), and terrain roughness all ramp in as competence rises. Build on the dr_scale band.
- WIDE per-leg ASYMMETRIC DR at the reproducing magnitude: joint_zero_bias_deg ~+-3, link_len_leg_pct ~+-4 (per-leg),
  + hard-world terrain (uneven ground / height-field, tilts, mid-stride pushes), + per-leg actuator asymmetry. Keep existing axes.

TRACK B -- warm-start the CURRENT BEST walker and RATCHET difficulty:
- launch_run --init-from the current best policy (per rl_index), continue training while progressively increasing the
  same wide DR + terrain + episode length. Curriculum FINETUNE, not from scratch. Cheapest path to a transferable gait.

RESEARCH ARM (parallel, lower priority): a TRANSFORMER/attention policy for the same task. NOT deployable yet -- needs a
torch-free numpy transformer runtime in np_policy.py (like the single-GRU port a813b837) BEFORE it can reach the robot;
build that only if it beats the GRU in sim.

Build missing infra as needed: difficulty-curriculum scheduler, uneven-ground/height-field terrain DR axis, larger-hidden
GRU cfg, (transformer runtime iff it wins). Report each arm through the ledger.


## CRITICAL CONSTRAINT for the adaptive-walker campaign (2026-09-24) — TRAIN UNDER THE DEPLOY SLEW CONTRACT
The campaign arms (Track A/B) MUST train under the DEPLOYABLE command-slew contract:
safety.max_delta_q_deg = 0.75 per tick (= 37.5 deg/s at 50 Hz), matching what the robot runner enforces.
Do NOT use the harsh-world bundle's bus.write_speed=4096 / max_delta_q=3.6 deg/tick: the robot runner does
NOT honor that (hard 37.5 deg/s clamp), so a policy trained at 3.6/tick is UNDEPLOYABLE (hardware-verified
2026-09-24 write_speed A/B: even perfect servo tracking under the 37.5 clamp still stalls/spins; the fix is
training a transferable gait WITHIN the clamp + robustness to per-leg miscalibration, not more slew freedom).
Every campaign arm: max_delta_q_deg=0.75, and the wide per-leg asymmetric geometry/zero DR is what buys transfer.


## CORRECTION 2026-09-24 — the adaptive campaign was closed on a MISCONFIG; re-open with a REAL slow ramp
The wide-DR adaptive campaign (cw-adapt50hz-*) was closed FAIL, but the exploration had a GAP:
- The arm named `...-widedr-slowramp-s0` used env.dr_stage_ramp_steps=25000000 — IDENTICAL to the fast
  `curr` arms (also 25M ramp / 40M budget). A GENUINELY slow ramp was NEVER tested. The warm-ratchet arms
  used an even faster 12M ramp. So "slow ramp failed" is FALSE — it was never run.
- Evidence it IS learnable: every failed arm's own verdict says "DR-0 nominal retention clean" — the policy
  WALKS at nominal DR and only collapses as DR ramps to the full wide setting over 25M. Useful gaits are
  clearly learnable in this sim (walkteach + the scratch envwide policies walk). The wide DR is not
  unlearnable; the 25M ramp is just too fast for the policy to track.

RE-OPEN (this is a NEW recipe, not a re-run of a closed one):
- GENUINELY SLOW ramp: env.dr_stage_ramp_steps ~= 120000000 over a --steps ~= 160000000 budget (ramp occupies
  most of training so DR grows slowly enough for the gait to adapt each step). This is the untested lever.
- Both TRACKS: (A) scratch bigger GRU-256/384; (B) warm-start --init-from the best converged walker champion
  (the combo-s0 the ratchet arms used, or the best envwide GRU). Multiple seeds. Keep safety.max_delta_q_deg=0.75.
- If a REAL slow ramp still collapses, THEN sweep a lower wide-DR ceiling (joint_zero_bias 2.0, link_len 0.03)
  to find the max learnable magnitude — do NOT jump to that before the slow ramp is actually tested.
- Do NOT re-close citing the prior slowramp arm — that was a 25M misconfig. Verify the launched
  env.dr_stage_ramp_steps is actually ~120M before trusting any 'slow ramp' label.


## ADD 2026-09-24 — TRANSFORMER arm on the same slow-ramp wide-DR adaptive task (deploy gate WAIVED)
Lukas: try a transformer too; do NOT gate it on deployability ("easy to deploy if it works"). The training
code already supports it (rl_move/sim/transformer_policy.py, train_ppo_sim --transformer: causal transformer
actor-critic over the env-side frame stack). Launch a TRANSFORMER research arm alongside the GRU slow-ramp arms:
- --transformer --cfg-set obs.history_frames=16 (the K-frame attention window = its temporal memory)
  --tf-width 256 --tf-layers 3 --tf-heads 4 (mid-size; scale if it trains well). FROM SCRATCH (a transformer
  cannot warm-start from a GRU/MLP checkpoint).
- SAME task as the GRU re-launch: REAL slow ramp env.dr_stage_ramp_steps ~= 120000000 over --steps ~= 160000000,
  full wide per-leg asymmetric DR + terrain, safety.max_delta_q_deg=0.75, multiple seeds.
- DEPLOYABILITY: WAIVED for now. If it wins in sim, build the torch-free numpy transformer runtime in
  np_policy.py (like the single-GRU port a813b837) THEN; do not skip the arm for lack of a runtime today.
