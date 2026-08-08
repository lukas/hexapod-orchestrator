# RL Plan — raw-joint policies to hardware candidates

Rev 2026-08-08b. Big goal: fluid real-world motion on the physical
hexapod — walking above all. History: `RL_LOG.md` + `archive/`.
**`archive/EXTERNAL_REVIEW_2026-08-08.md` is the binding external
review (GPT + Claude, disagreements resolved): it sets the priority
sequence, walk-reward strategy, and autonomy hardening below. Core
diagnosis: the shuffle is a reward-landscape problem; four shaping
levers refuted — stop iterating penalty coefficients.**

## State (evidence)

- Main line: **18-dim raw joint targets** (body-IK line concluded —
  its flat-rise was a noise-fragile choreography; champion archived at
  `policies/best_flat_rise_run06_1540704.zip`; never BC from it).
- **Stand↔belly: SOLVED at DR 1.0**, twice (`cw-stand-dr10`,
  `cw-stance-dr10`). Frozen. Don't mutate; flag any eval where
  rise/lower drops below 5/6; never warm-start stand work from an
  eroded checkpoint.
- **Walk: scalars pass, motion is BAD.** Tracks 0.02–0.06 m/s at
  DR 0.4 (`cw-walk-dr04b`, sto 4/6 @ vel_err 0.028, re-validated
  08-08; honestly 0/N under the gait-validity gate) but videos show a
  shuffling 3–5-leg exploit with legs parked vertically — nothing
  like a gait that could transfer. NOT HARDWARE-READY until videos
  show all six feet cycling contact/swing. Refuted levers: manual
  widening (→0.08, →0.07), 3× progress reward, all-modes
  k_flag_leg=5.0 (rise/raise collapsed), walk-only k_flag_leg
  (`cw-walk-flagw` + twin, both 0/6 gait-valid — flag penalty DEAD),
  and **speed pressure (`cw-walk-speedhi` 08-08): commands 0.10–0.15
  did NOT force stepping — speed stuck at ~0.033 m/s, vel_err
  0.08–0.11, leg 3 parked 12/12, a second leg flagged. Curriculum
  frontier stays slow→fast.** Also: **walk-line `lower` is 0/6 in the
  whole lineage incl. champion dr04b** (first measured cycle 11) —
  interference erosion covers rise AND lower; lower stays a walk-line
  eval tripwire; end-state policy comes from the stance line or a
  merge.
- **Raise: DEMOTED TO CANARY (08-08).** Stuck 2–5/6 in every lineage;
  `cw-stance-raisemix` (2× raise samples) refuted the mix hypothesis
  (3/6 det, 4/6 sto). Classification: all failures = near-miss
  under-lift 6–8 mm, no falls/tilt/current; raise executes on ~4 legs
  (legs 2/4 unloaded even in passes). Only remaining lever is
  coefficient iteration (forbidden, review §0/§7). Stays in canaries
  + eval as a tripwire; no more compute.
- Seed twins before cw-walk-flag/-s1 were bit-identical clones
  (set_random_seed fix landed 08-08; earlier "twin variance" and
  best-of-2 conclusions discarded). Twin eval spread of identical
  weights (vel_err 0.026 vs 0.043) calibrates few-episode eval noise.
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
- **Fixed-seed canaries + regression auto-stop — LANDED 08-08**
  (review §5a/§5c; default-on for warm starts, `--no-canary` opts
  out): identical rise flat/bridge/crouch + lower cases every probe;
  parent baseline at launch; groups the parent passed 2/2 are
  protected; 3 consecutive full-group failures auto-terminate.
  Randomized ≥20-ep harness stays the promotion standard.
- **Noise-response curve per champion:** success at action std
  0/.02/.05/.10/.15/.20, stored with the checkpoint. Deterministic
  100% with a cliff at small std will erode in any fine-tune.
- **Gait sanity lives in the evaluator, not only reward:** per-foot
  contact duty cycle, swing/touchdown counts, swing length, clearance,
  slip, loading, joint occupancy, supporting-leg count. **A walking
  checkpoint is INVALID if any leg is persistently sacrificed,
  regardless of velocity error.** Flag-leg detection stays an eval
  gate permanently, whatever happens to its reward term. Eval
  definitions must be independent of reward terms.
- **Current:** record per-servo max, p95/p99, time above soft
  threshold, cross-leg imbalance. Aggregate current is insufficient
  (18×0.6 A ≠ 3×2.4 A). No hot legs.
- Champions: keep-best by eval score, never keep-last; append-only
  read-only files, separate per skill (stand/recovery, lower, walk,
  hardware candidate).

## Reward routing

Interference is proven three times (stance clearance killed raise;
walk erodes rise; global flag-leg charge collapsed rise). GLOBAL:
safety, joint limits, excess current, violent motion, smoothness.
MODE-SPECIFIC: walk = tracking/gait/contact/flag-leg; rise/lower =
progress/contact; hold = attitude/stance/load. New terms declare
routing up front — no ad-hoc exemptions.

## Skill notes

- **Stand↔belly (frozen):** anti-choreography DR already in: hold
  timing U(0.5,5) s, jittered/lower-ending starts, latency/deadband,
  friction, mass/CoM, joint-zero error. Gates beyond height: pose
  reached (by start kind), zero safety terms, no sustained
  over-threshold servo, no violent impact, quiescent at end.
- **Walk:** success = commanded forward motion with visible
  alternating contacts on ALL SIX legs — judged by gait metrics AND
  video. Refuted: flag penalty (both routings), speed pressure
  (`cw-walk-speedhi` FALSE branch 08-08); **no penalty-coefficient
  iterations, period** (review §0). Escalation (review §2):
  (c) **Weak alternating-tripod phase reward** (Siekmann-style
  periodic reward composition) — **LAUNCHED cycle 11 as
  `cw-walk-phase`**: actor sees sin/cos of a 1 Hz clock (+2 obs via
  zero-column transplant, `goal.walk_phase_obs`), modest
  contact-agreement reward (`reward.k_phase_contact=1.0`, walk-routed,
  runs only while velocity is commanded; parked/dragged legs average
  50% agreement = zero net), NO prescribed joints/trajectories/rigid
  timing. Rationale: penalties failed because PPO pays fines; this
  pays stepping itself, densely. (b) Cheap: per-servo current on
  shuffle reels — imbalance 1.6–1.9, no hot dragging leg; keep open.
  (d) Dense 9-term step decomposition stays LAST-resort. Lateral/yaw
  only after forward is real. Rise/lower erosion persists → plan for
  walk-specialist + later merge/distillation.
- **Deployable walk obs, in order:** (1) asymmetric PPO (hardware-obs
  actor, privileged critic — in flight, `cw-walk-aac`); (2) +history,
  frame stack vs GRU (~300 ms = online system ID); (3) distillation
  only if those fail. **nv baseline CALLED at 8M (cycle 11): sto walk
  0/6 gait-valid @ vel_err 0.035, flag leg unchanged — that is the
  bar aac/aac-s1b must beat at 28.76M cum. nv line closed.**
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
8. then a **large frozen-policy eval**: hundreds of episodes, nominal
   / full DR / bad corners; keep video+telemetry of failures/worst-N.

Deployment: existing hardware safety rules (set-zero-here, operator
present, 25 Hz, limp-on-anomaly), supported sessions, order quiet
hold → lower → rise → walk. Every session logs sim↔real divergence
(tilt, q/dq, currents, gyro, timing, SafetyLayer) to recalibrate DR.

## Compute

- 6 pods on **two ~128-core nodes** (08-08: g142d86 = friction/
  long5m/s3; g129004 = lower/s4/walk; loadavg is host-wide). 12 slots
  (cap 10 + 2 smoke) are LAUNCH slots, not throughput: a 48-env run
  needs ~50–60 cores; >2–3 heavy runs per NODE starve each other (5
  on g129004 → 100–400 fps vs ~570). Budget ~4–5 fast runs total;
  per-run log `/tmp/train_<run>.log`.
- Keep `--eval-every`/`--video-every` ≥200k; periodic eval/video now
  runs in a background worker process (validated 08-08, ~free).
- Pods answer architecture-level questions, not micro reward tweaks;
  multi-seed only after a config wins.

## Queue (in flight → next; ordering per external review §1)

In flight: `cw-walk-aac` + `cw-walk-aac-s1b` (asym AC — review item
1; judge vs the called nv 8M baseline), `cw-walk-lp` + `cw-walk-lp-s1b`
(LP speed curriculum), `cw-walk-phase` (alternating-tripod phase
reward, launched cycle 11 on long5m, warm from dr04b via obs-pad
transplant).

1. Eval aac/aac-s1b and lp/lp-s1b as they finish (gait-validity gate;
   lower now in walk-line eval modes as a tripwire).
2. Temporal deployable actor (frame stack vs GRU) on the best of
   `aac`/nv-8M-baseline — next architecture step after (1).
3. If `cw-walk-phase` produces real stepping: consolidate, then
   combine with the aac actor (transplant order: phase obs shifts the
   privileged dims — not co-launchable with --asym-critic yet).
4. Contact-from-proprioception auxiliary head, after (2). Dense
   step-decomposition and model-size sweep stay last.

Infra LANDED 08-08 cycle 9 (review §5, §8): fixed-seed canaries +
regression auto-stop, harness gait-validity gate, experiments.json
ledger + watcher dedupe.

## Done =

One policy (or per-skill champion set) that from stance: holds
quietly, lowers/rises on command with randomized timing, walks
forward with real alternating contacts and balanced currents — all
passing visual eval + checkpoint policy + the hardware gate. Then
freeze the candidate and begin supported sim-to-real validation.
