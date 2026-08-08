# RL Plan — raw-joint policies to hardware candidates

Rev 2026-08-08. Big goal: fluid real-world motion on the physical
hexapod — walking above all. History: `RL_LOG.md`,
`archive/RL_CAMPAIGN_REVIEW_2026-08-08.md`. External priorities:
`archive/HEXAPOD_RL_LITERATURE_REVIEW_2026-08-08.md`.

## State (evidence)

- Main line: **18-dim raw joint targets** (body-IK line concluded —
  its flat-rise was a noise-fragile choreography; champion archived at
  `policies/best_flat_rise_run06_1540704.zip`; never BC from it).
- **Stand↔belly: SOLVED at DR 1.0**, twice (`cw-stand-dr10`,
  `cw-stance-dr10`). Frozen. Don't mutate; flag any eval where
  rise/lower drops below 5/6; never warm-start stand work from an
  eroded checkpoint.
- **Walk: scalars pass, motion is BAD.** Tracks 0.02–0.06 m/s at
  DR 0.4 (`cw-walk-dr04b`, sto 4/6 @ vel_err 0.028) but videos show a
  shuffling 3–5-leg exploit with legs parked vertically — nothing
  like a gait that could transfer, even with perfect dynamics. Treat
  the lineage as NOT HARDWARE-READY until videos show all six feet
  cycling contact/swing. Both manual range widenings (→0.08, →0.07)
  regressed; tripled progress reward did nothing.
- **Raise:** stuck 2–5/6 in every lineage. Undiagnosed.
- Warm-start "seed twins" before 08-08 were bit-identical clones
  (PPO.load re-seeded from ancestor; fixed via set_random_seed).
- MuJoCo 3.11 shifted current readings (quiet-hold peak 2.46→2.60 A,
  right at the 2.5 A breaker). Re-validate torque→current calibration
  before trusting any current gate for hardware.

## Architecture (hold constant unless something fails)

- **Action:** 18 joint targets in [-1,1] → absolute angles (yaw ±35°,
  hip −80..30°, knee −20..150°) through SafetyLayer (~2°/tick rate
  limit, axis clips, tilt/current trips) — same path hardware uses.
- **Actor obs — deployable only:** joint pos/vel, comp-filter tilt,
  gyro, per-servo current, prev action, goal block, walk velocity
  refs. Measured vx/vy is privileged, sim-only.
- **Asymmetric actor–critic:** privileged state (true velocity,
  contacts, pose) may go to the critic only; it vanishes at deploy.
- **Temporal history beats bigger MLPs:** ~300 ms obs/action history
  (8 frames @ 25 Hz) = implicit system ID. Ablate frame-stack vs
  small GRU. Model-size sweeps rank behind all of this.
- Deterministic inference for eval and deployment, always.

## Evaluation rules

- **A checkpoint is not a result until an exact-path visual eval**
  (`eval_checkpoint.py`: same env/wrappers/reset as training eval,
  video + telemetry overlays). Scalars have repeatedly hidden
  exploits (flag leg, shuffle, lucky crouch draws). If a checkpoint
  scores well but looks wrong, the metric is the bug. Video verdicts
  are written pathology-first with an explicit hardware-ready yes/no;
  operator finding 2026-08-08: past summaries oversold broken motion.
- ≥20 episodes for gate decisions (2-episode evals are binomial
  noise). Split all rise/lower stats by start kind. Eval at DR 0 and
  the run's own DR.
- **Noise-response curve per champion:** success at action std
  0/.02/.05/.10/.15/.20, stored with the checkpoint. Deterministic
  100% with a cliff at small std will erode in any fine-tune.
- **Gait sanity lives in the evaluator, not only reward:** per-foot
  contact fraction, max/sustained clearance, swing count, stride,
  slip, joint occupancy, time near limits, supporting-leg count.
  Diagnose pathology before changing rewards.
- **Current:** record per-servo max, p95/p99, time above soft
  threshold, cross-leg imbalance. Aggregate current is insufficient
  (18×0.6 A ≠ 3×2.4 A). No hot legs.
- Champions: keep-best by eval score, never keep-last; append-only
  read-only files, separate per skill (stand/recovery, lower, walk,
  hardware candidate).

## Reward routing

Interference is proven (stance clearance fixed tripod, killed raise;
walk erodes rise). GLOBAL terms: safety, joint limits, excess
current, violent motion, universal smoothness. MODE-SPECIFIC:
walk = tracking/gait/contact; rise/lower = progress/contact/controlled
motion; hold = attitude/stance/load. New terms declare routing up
front — no ad-hoc exemptions.

## Skill notes

- **Stand↔belly (frozen):** anti-choreography DR already in: hold
  timing U(0.5,5) s, jittered/lower-ending starts, latency/deadband,
  friction, mass/CoM, joint-zero error. Gates beyond height: pose
  reached (by start kind), zero safety terms, no sustained
  over-threshold servo, no violent impact, quiescent at end.
- **Walk:** success = commanded forward motion with visible
  alternating contacts on ALL SIX legs — judged by gait metrics AND
  video. `reward.k_flag_leg` (clearance >50 mm allowance, all modes)
  is the current lever. **Learning-progress curriculum replaces
  manual widening:** bucket commands (0.02–0.03 … 0.10–0.12 m/s),
  track per-bucket tracking/gait/falls/slip/stride/current/progress,
  sample buckets that are improving; command-speed→performance curve
  as a W&B metric. Lateral/yaw only after forward is real. If rise
  erosion survives the gait fix, train walk separately, merge later.
- **Deployable walk obs, in order:** (1) asymmetric PPO (hardware-obs
  actor, privileged critic); (2) +history, frame stack vs GRU;
  (3) distillation (`distill_joint_policy.py`) only if those fail.
  `cw-walk-nv` (zeroed velocity obs) is the naive baseline to beat.
  If exploits persist after gait metrics + curriculum: a WEAK
  alternating-tripod contact-phase prior, never hard trajectories.
- **DR progression:** 0–0.2 until the skill exists, 0.4 once
  reliable, broader after. Randomize the realistic uncertainties
  (friction, latency, deadband, strength, mass/CoM, joint-zero, IMU
  mount); never so hard the task disappears first.

## Hardware candidate gate (all required; robot already cooked a motor)

1. clean exact-path visual eval, DR 0 + DR 0.2, fixed seeds
2. ≥20-ep success on target skill, zero safety terminations
3. no systematic hot leg (post current-recalibration)
4. robust across friction/actuator draws
5. per-joint deployment envelopes from successful sim trajectories;
   hardware bridge clamps to those, not full servo range
6. low SafetyLayer intervention rate (reliance = failure)
7. insensitive to obs noise at hardware levels
8. then a **large frozen-policy eval**: hundreds of episodes across
   nominal / full DR / bad corners; keep video+telemetry of all
   failures and worst-N. Eval is cheap vs training.

Deployment: existing hardware safety rules (set-zero-here, operator
present, 25 Hz, limp-on-anomaly), supported sessions, order quiet
hold → lower → rise → walk. Every hardware session logs sim↔real
divergence (roll/pitch, q/dq, currents, gyro, timing, SafetyLayer)
to recalibrate DR from data.

## Compute

- 4 pods × 128 cores. One 48-env run saturates ~50–60 cores → **two
  48-env runs per pod** at near-full speed (guardrails:
  max_runs_per_pod 2, per-run log `/tmp/train_<run>.log`).
- Blocking eval/video cost ~65% of wall clock at old 20k/25k cadence;
  keep `--eval-every`/`--video-every` ≥200k (background eval work in
  progress to remove the stall entirely).
- Pods answer architecture-level questions, not micro reward tweaks;
  multi-seed only after a config wins.

## Queue (in flight → next)

In flight: `cw-walk-flag` + seed twin (flag-leg fix, gate = tracking
AND no-flag-leg video AND rise retention), `cw-walk-nv` (baseline).

1. Learning-progress speed curriculum on the walk champion.
2. Asymmetric actor–critic; must beat `cw-walk-nv`.
3. Temporal deployable actor (frame stack vs GRU) on the better of
   (2)/`nv`.
4. Raise diagnosis: raise-heavy mix on the even-stance DR 1.0
   champion.
5. Lower end-posture: `k_flag_leg` on the stance line once the
   flag-leg run proves the term.

## Done =

One policy (or per-skill champion set) that from stance: holds
quietly, lowers/rises on command with randomized timing, walks
forward with real alternating contacts and balanced currents — all
passing visual eval + checkpoint policy + the hardware gate. Then
freeze the candidate and begin supported sim-to-real validation.
