# RL Plan — Next Phase: raw-joint policies to hardware candidates

2026-08-07. Successor to the day's two experiment lines; incorporates
external (GPT) review of the CoreWeave results. `RL_PLAN.md` remains
the Phase-1 reference and status log; this file is the forward plan.

## 0. Where we are (evidence, not aspiration)

Two lines ran today:

- **Body-IK line (6-dim actions, local, runs 01–10):** solved
  hold/lean/track/unload/raise and crouch-rise. Flat-belly rise was
  achieved once (run 06 champion, 9/12 deterministic) but **eroded in
  every continuation run** (07/08/09 → 0/6). Root cause measured, not
  guessed: the skill is a ~9 s knife-edge choreography that fails 0/12
  under sampling noise std ≥ 0.10 and only survives at std ≤ 0.05;
  PPO optimizes the noisy return, so it rationally abandons the skill
  (run 10 at std 0.05: erosion slowed — flat 1–2/6 — but not stopped).
  **Line concluded.** Champion archived
  (`policies/best_flat_rise_run06_1540704.zip`).
- **Raw-joint line (18-dim actions, CoreWeave):** the main line, six
  rounds in (see RL_LOG.md + archive/RL_CAMPAIGN_REVIEW_2026-08-08.md).
  Stand↔belly is SOLVED at full DR 1.0, twice over: plain
  (`cw-stand-dr10`) and even-stance (`cw-stance-dr10`, six-footed
  hold, imbalance ~1.4–1.9). Walk tracks 0.02–0.06 m/s commands at
  DR 0.4 (`cw-walk-dr04b`, sto 4/6 @ vel_err 0.028) but the whole
  walk lineage carries a **vertical flag leg** (5-leg shuffle, one
  hind leg parked overhead) that scalars never surfaced — reward gap:
  the clearance penalty skipped walk/rise/lower/raise. Both range
  widenings (0.08, 0.07) failed. Raise is stuck at 2–5/6 everywhere.
  NOTE: every warm-started "seed twin" before round 7 was a bit-identical
  clone (PPO.load re-seeds from the ancestor; fixed for real 08-08).

Decision (agreed with external review): **the 18-joint raw action
space is the main RL line.** Body-IK survives only as the human/teleop
interface (it maps 1:1 onto the HTTP body-offset API) and as a
scripted baseline for reward audits. Do not BC from it.

Why this matches the deeper lesson: fixed-foot IK cannot express
foot-moving skills, and its curl channel concentrated a whole
behavior into one fragile dimension. Raw joints let dense
whole-configuration progress rewards pay every step of the way — the
noise-fragility saga never appeared on that line.

## 1. Policy architecture (hold constant unless something fails)

- **Action:** 18 joint targets in [-1,1] → absolute angles over
  conservative per-axis limits (yaw ±35°, hip −80..30°, knee
  −20..150°), through the existing SafetyLayer: per-tick rate limit
  (max_delta_q_deg ≈ 2°/tick), axis clips, tilt/current trips. "Raw"
  never means unfiltered — same path hardware will use.
- **Obs:** joint pos/vel, complementary-filter tilt, gyro, per-servo
  current estimate, prev action, goal block. Walk adds velocity refs;
  `cw-walk2` also observes measured vx/vy — **privileged, sim-only**
  (see §5).
- **No recurrence for now.** If a concrete failure demands history,
  try frame-stacking before LSTM.
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

**Addition beyond the external review (IK-line lesson):** also probe
each champion **stochastically at the training std**. A skill that
only works deterministically will erode in any future fine-tune; we
want to know the noise margin of every skill we plan to keep, and
noise-jittered starts/timing (§3) are the cheap way to widen it.

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

Command ladder: consolidate 0.02–0.06 with a clean gait BEFORE any
re-widening (two widen failures say range is not the bottleneck);
lateral/yaw only after forward walking is clearly real. Rise erosion
inside walk runs persists (flat-rise flaps 0–5/6 across walk evals) —
if it survives the gait fix, train walk separately and merge later.

**Privileged velocity:** measured vx/vy in obs is fine for a
teacher/proof-of-concept, unusable on hardware (no velocity sensor).
Deployable path, in order: (1) frame-stacked proprioception/IMU
student; (2) teacher→student distillation from the privileged policy
(scaffolding exists in `distill_joint_policy.py`); (3) recurrent
policy only if both fail. Sim-first; don't block the teacher run on
this.

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
twins were clones).

1. **Gait quality:** kill the flag leg (`k_flag_leg`) on the walk
   champion at DR 0.4, slow range, seed twin alongside; gate = scalar
   tracking AND no-flag-leg video AND rise retention.
2. **Walk student (deployable obs):** `goal.walk_obs_body_vel=0`
   (zeroed privileged velocity, warm-start compatible); frame-stack
   or distillation only if the zeroed-obs run fails.
3. **Raise diagnosis:** raise-heavy goal mix on the even-stance
   DR 1.0 champion; the skill has hovered 2–5/6 in every lineage.
4. **Lower end-posture:** apply `k_flag_leg` to the stance line (its
   lower ends with legs aloft) once (1) proves the term safe.
5. Seeds ×3 on whichever of (1)–(3) produces a champion.

## 10. Definition of done for this phase

From a normal stance, one 18-joint policy (or a small set of
per-skill champions): holds quietly, lowers to belly and rises back
on command with randomized timing, and walks forward on command with
real alternating contacts and sane, balanced currents — all passing
the §2 visual eval and the §7 checkpoint policy, with the §8 gate
green. Then freeze the hardware candidate and begin supported
sim-to-real validation under the safety rules.
