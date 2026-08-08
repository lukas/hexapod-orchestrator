# RL Plan — Next Phase: raw-joint policies to hardware candidates

2026-08-07, revised 08-08 to fold in the external literature review
(`archive/HEXAPOD_RL_LITERATURE_REVIEW_2026-08-08.md` — asymmetric
actor–critic, learning-progress curriculum, temporal actors, reward
routing; those outrank any model-size sweep).

## 0. Where we are (evidence, not aspiration)

- **Body-IK line (6-dim actions): concluded.** Solved everything but
  flat rise robustly; its one flat-rise champion was a knife-edge
  choreography that failed 0/12 at action std ≥ 0.10, so PPO rationally
  abandoned it in every continuation. Champion archived
  (`policies/best_flat_rise_run06_1540704.zip`); details in
  archive/RL_CAMPAIGN_REVIEW_2026-08-08.md.
- **Raw-joint line (18-dim actions, CoreWeave): the main line** (per
  external review; do not BC from IK). Stand↔belly is SOLVED at full
  DR 1.0, twice over (`cw-stand-dr10`, `cw-stance-dr10`). Walk tracks
  0.02–0.06 m/s at DR 0.4 (`cw-walk-dr04b`, sto 4/6 @ vel_err 0.028)
  but the whole lineage carries a **vertical flag leg** (5-leg shuffle)
  that scalars never surfaced; both range widenings failed. Raise is
  stuck at 2–5/6 everywhere. Warm-start "seed twins" before 08-08 were
  bit-identical clones (PPO.load re-seeded from the ancestor; fixed).

## 1. Policy architecture (hold constant unless something fails)

- **Action:** 18 joint targets in [-1,1] → absolute angles over
  conservative per-axis limits (yaw ±35°, hip −80..30°, knee
  −20..150°), through the existing SafetyLayer: per-tick rate limit
  (max_delta_q_deg ≈ 2°/tick), axis clips, tilt/current trips. "Raw"
  never means unfiltered — same path hardware will use.
- **Obs (actor):** deployable-only — joint pos/vel, complementary-filter
  tilt, gyro, per-servo current estimate, prev action, goal block. Walk
  adds velocity refs; measured vx/vy is **privileged, sim-only** (§5).
- **Asymmetric actor–critic (lit review #1):** privileged state (true
  body velocity, exact contacts, pose) goes to the CRITIC, which
  vanishes at deployment. Never into the actor.
- **Temporal history over bigger MLPs (lit review #2):** ~300 ms of
  obs/action history (8 frames @ 25 Hz) acts as implicit system ID
  (velocity, latency, contact state). Ablate frame-stack vs small GRU;
  a 10–16x MLP sweep ranks behind both.
- Deterministic inference for eval and deployment, always.

## 2. Validate checkpoints by looking at them (before anything else)

Aggregate metrics have lied to us repeatedly (pooled rise stats hid a
0% flat rate; "rise 4/4" was four lucky crouch draws; walk return
+249 was a shuffle). Standing rule: **a checkpoint is not a result
until it has passed an exact-path visual eval.**

Build one `eval_checkpoint.py` harness (or extend `view.py` /
`preflight.py`) that loads a checkpoint through the *identical* env,
wrappers, and reset path as automated eval and records video with
telemetry overlays:

- 18 policy outputs; target vs measured joint angles
- roll/pitch/height vs refs; per-servo current (peak highlighted)
- foot contacts and slip; SafetyLayer interventions
- for walk: commanded vs measured body velocity

Protocol per champion: deterministic policy, fixed seeds, DR 0 first
then DR 0.2, ≥20 episodes for gate decisions (2-episode evals are
binomial noise — proven twice today). Split every rise/lower stat by
start kind. Queue: `cw-lower-smooth2`, `cw-friction`, `cw-long5m`,
latest `cw-walk2`. If a checkpoint scores well but looks wrong, the
metric is the bug — fix it before training anything else.

**Noise-response curve as champion metadata (IK-line lesson):** probe
each champion at action std 0 / 0.02 / 0.05 / 0.10 / 0.15 / 0.20 and
store the success-vs-std table with the checkpoint. A deterministic
100% with a cliff at tiny noise is not the same skill as one with
margin, and will erode in any future fine-tune.

**Gait/configuration sanity belongs in the evaluator, not only reward**
(flag leg was a specification exploit that scalars missed): per-foot
contact fraction, max clearance and sustained-clearance duration, swing
count, stride, slip, joint-angle occupancy, time near limits, number of
supporting legs. The evaluator should catch pathology first; change
rewards only after the failure is understood.

## 3. Stand ↔ belly, robust — the flagship skill

`cw-lower-smooth2` lineage continues. Anti-choreography measures (some
already in): randomize rise hold timing (`rise_hold_min_s` ~ U(0.5,5)),
randomize starting joint config around flat (± jitter, and lower-run
endings as rise-run starts), actuator latency/deadband DR, friction
range, mass/CoM, modest joint-zero error (the hardware failure mode
that caused the 2026-08-06 incident — train for it).

Success gates, per external review, more than final height:

1. target pose reached (split by start kind, ≥20 eps)
2. zero safety terminations
3. no servo above soft current threshold for a sustained window
4. no violent impact (peak body accel / contact impulse bound)
5. quiescence at completion (low residual gyro/joint velocity)

Champion selection by eval score, never by last checkpoint.

**Freeze it once it passes** (lit review / HoST): stand↔belly at DR 1.0
is solved twice over. Do not keep mutating a solved skill or retrofit
new architecture into it; locomotion work must not silently erase it.

## 4. Current distribution — no hot legs

Sum-square current can't tell 18 servos at 0.6 A from 3 at 2.4 A.
`reward.k_current_max` (quadratic on peak per-servo current) exists;
extend the **eval side** to record per-servo max, p95/p99, time above
soft threshold, and cross-leg imbalance. A policy does not pass on
aggregate current alone.

Prerequisite: **re-validate torque→current calibration under MuJoCo
3.11** (A/B showed quiet-hold peaks reading 2.46→2.60 A across the
upgrade — that sits exactly AT the 2.5 A breaker, so trip statistics
are currently not trustworthy). Do this before treating any current
gate as hardware-meaningful.

**Reward routing, formalized (lit review #4):** interference is a
proven failure mode here (stance clearance fixed the tripod, killed
`raise`; walk erodes rise). Split terms explicitly: GLOBAL = safety,
joint limits, excessive current, violent motion, universal smoothness.
MODE-SPECIFIC = tracking/gait terms for WALK, progress/contact terms
for RISE/LOWER, attitude/stance/load terms for HOLD. New terms declare
their routing up front instead of accumulating ad-hoc exemptions.

## 5. Locomotion — real stepping, not exploits

Goal, stated bluntly: commanded forward motion with visibly
alternating foot contacts ON ALL SIX LEGS. Velocity error alone
cannot verify that (proven again: the flag-leg shuffle passed its
scalar gates). Judge by the harness gait metrics AND video: duty
cycles, stride, slip, swing count, current distribution — and reject
any policy that makes speed via dragging, slipping, oscillation, or
sacrificing a leg. `reward.k_flag_leg` (clearance above a 50 mm
allowance, all modes) is the current lever; walk-quality gates from
here on include "no foot above allowance except during swing".

**Learning-progress curriculum replaces manual widening (lit review
#3).** Two abrupt widenings regressed; tripled progress reward did
nothing — this is a curriculum problem, not a reward-magnitude one.
Bucket the command space (0.02–0.03, …, 0.10–0.12 m/s), track per
bucket: tracking error, valid-gait success, falls, slip, stride,
current, and recent learning progress; preferentially sample buckets
that are currently improving, not solved or impossible ones. Make the
command-speed → performance curve a first-class W&B metric.
Lateral/yaw only after forward walking is clearly real. Rise erosion
inside walk runs persists (flat-rise flaps 0–5/6 across walk evals) —
if it survives the gait fix, train walk separately and merge later.

**Privileged velocity:** measured vx/vy in obs is fine for a
teacher/proof-of-concept, unusable on hardware (no velocity sensor).
Deployable path, in order (lit review #1–2): (1) **asymmetric PPO** —
hardware-obs actor, privileged critic; (2) add ~300 ms obs/action
history to the actor, comparing frame stack vs small GRU;
(3) teacher→student distillation (`distill_joint_policy.py`) only if
those fall short. `cw-walk-nv` (velocity obs zeroed, no history) is
in flight as the naive baseline the asymmetric runs must beat.

If exploitation persists after gait metrics + flag-leg + curriculum:
consider a WEAK alternating-tripod contact-phase prior (soft, PPO
keeps freedom) — never hard-coded joint trajectories.

## 6. Domain randomization progression

Skill first, robustness second: DR 0–0.2 until the skill exists;
0.4 once reliable (already validated for rise); broader after.
Prioritize the realistic uncertainties: friction, latency, deadband,
torque strength, mass/CoM, joint-zero error, IMU mounting. Never
randomize so hard the task disappears before the skill exists.

## 7. Checkpoint policy

- Champions kept separately per skill: stand/recovery, lower, walk,
  and a "hardware candidate" (may lag the others on purpose).
- Keep-best by ≥20-episode fixed-seed deterministic eval, never
  keep-last (three runs today destroyed a working skill while their
  training returns looked fine).
- Every champion gets the §2 visual eval and a stochastic probe
  before promotion. Champions are read-only files; training always
  writes elsewhere.

## 8. Hardware candidate gate (nothing touches the robot before this)

A raw-joint policy commands 18 servos directly on a robot that has
already cooked a motor. Gate, all items required:

1. clean exact-path visual eval (§2), DR 0 and DR 0.2, fixed seeds
2. ≥20-episode success on the target skill, zero safety terminations
3. no systematic hot leg (§4 metrics, post-recalibration)
4. robustness across friction/actuator draws (cw-friction-style)
5. conservative joint-range usage — derive **per-joint deployment
   envelopes from successful sim trajectories** and clamp the
   hardware bridge to those, not the full servo range
6. low SafetyLayer intervention frequency in sim (interventions are
   evidence the policy relies on the guardrail)
7. deterministic, and behavior verified insensitive to obs noise at
   hardware levels
8. **large frozen-policy eval** (lit review #11): dev promotion keeps
   the ≥20-episode gate, but a hardware candidate gets hundreds of
   frozen-policy episodes across nominal, full DR, and explicit bad
   corners, retaining video/telemetry for all failures and worst-N.
   Evaluation is cheap relative to training — exploit that.

Every hardware session must also improve the simulator (lit review
#13): run the same trajectories in sim and hardware, quantify
divergence (roll/pitch, q/dq, currents, gyro, timing, SafetyLayer
events), and feed it back into calibration and DR — moving from broad
guessed DR toward empirically calibrated uncertainty.

Deployment protocol itself stays under the existing hardware safety
rules: set-zero-here before any absolute pose, operator present and
explicitly authorizing each session, 25 Hz, limp-on-anomaly. First
hardware sessions are supported (robot on a stand / hand-spot), single
skill, starting with quiet hold, then lower (it starts from a stable
stance and ends on the belly — failure is a controlled descent), then
rise, then walk. Not before `cw` champions pass the full gate.

## 9. CoreWeave allocation (next runs, in priority order)

Use pods for architecture-level questions, not micro reward tweaks;
multi-seed only after a config wins (and only post seed-fix — earlier
twins were clones). Pods have 128 cores and can host TWO 48-env runs
each at near-full speed; keep `--eval-every`/`--video-every` ≥ 200k
(dense eval measured at ~65% of wall clock) and one log file per run.

In flight: **flag-leg fix** (`cw-walk-flag` + seed twin) and the naive
zeroed-velocity baseline (`cw-walk-nv`). Next, per lit review §14:

1. **Learning-progress speed curriculum** (§5) on the walk champion —
   command buckets + adaptive sampling instead of manual widening.
2. **Asymmetric actor–critic:** hardware-obs actor, privileged critic;
   must beat `cw-walk-nv` to justify the machinery.
3. **Temporal deployable actor:** frame stack vs small GRU on
   hardware-realistic obs, on top of whichever of (2)/`nv` is ahead.
4. **Raise diagnosis:** raise-heavy goal mix on the even-stance
   DR 1.0 champion; the skill has hovered 2–5/6 in every lineage.
5. **Lower end-posture:** apply `k_flag_leg` to the stance line (its
   lower ends with legs aloft) once the flag-leg run proves the term.

Model-size experiments move BEHIND all of the above.

## 10. Definition of done for this phase

From a normal stance, one 18-joint policy (or a small set of
per-skill champions): holds quietly, lowers to belly and rises back
on command with randomized timing, and walks forward on command with
real alternating contacts and sane, balanced currents — all passing
the §2 visual eval and the §7 checkpoint policy, with the §8 gate
green. Then freeze the hardware candidate and begin supported
sim-to-real validation under the safety rules.
