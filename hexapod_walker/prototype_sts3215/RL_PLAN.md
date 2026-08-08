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
- **Stand↔belly: heights SOLVED at DR 1.0** (`cw-stand-dr10`,
  `cw-stance-dr10`) — **but posture-strict eval (cycle 12) caveats the
  jewel: stance-champ lower ends 0/12 with legs 0/2/4 hoisted (leg 4
  vertical 244–281 mm); rise 5/12 (crouch/bridge starts leave legs 2/4
  up); hold 12/12 clean.** `cw-stance-posture` (in flight) prices the
  fix. Flag any eval where rise/lower height drops below 5/6; never
  warm-start stand work from an eroded checkpoint.
- **Walk: no valid gait exists in any lineage.** dr04b lineage is
  0-for-9 on gait validity (widen ×2, 3× progress, flag ×2, speed, LP,
  phase, asym, 8M) with lower 0/6 and universal end-posture failure —
  **RETIRED as warm-start source for gait work** (cycle 12). Phase
  reward refuted in BOTH basins (warm: shuffle; stance-init @ audited
  std 1.0: tripod park). **The TRIPOD PARK is the shared attractor**
  (lp tower, aac-s1c det, phase-stance2): planting 3 legs and parking
  3 avoids all stepping costs and nothing prices it — measured cycle
  12: a flagged leg draws 0.24 A vs 0.28–0.44 A per supporting leg,
  and the linear current charge is distribution-blind. Any future
  walk reward must price the park (time-averaged per-leg load), or
  change capability (temporal actor), not coefficients.
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
- **PPO settings (audit 08-08, binding —
  `archive/BEST_PRACTICES_AUDIT_2026-08-08.md`):** from-scratch /
  basin-escape arms train with `log_std_init 0.0` (std 1.0) and
  `ent_coef 0.005–0.01` — the historic 0.37/0.001 is 3–10x below
  field standard and taints pre-audit from-scratch refutations. All
  runs set `target_kl≈0.02` (destructive-update guard). Entropy
  collapse = health alarm. New mechanisms need a probe smoke first;
  reward changes trigger the scale audit; mirror-symmetry
  augmentation queued post-phase-verdict.

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
- **End-posture gate (cycle 12, default ON in the harness):** stand-
  ending modes must finish with all six feet ≤20 mm of their grounded
  reference (lower: ≤60 mm, no hoisted legs). Success counts since
  2026-08-08 are posture-strict; older numbers are height-only.
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
  video. Refuted: flag penalty (both routings), speed pressure, LP
  curriculum, **weak phase-contact reward in both basins (cycle 12:
  zero-net agreement cannot outbid the cost savings of the tripod
  park)**; **no penalty-coefficient iterations, period** (review §0).
  Remaining rungs, in order: (1) **temporal actor** (frame stack ~8 @
  25 Hz, code task — obs history must be env-side so harness/hardware
  match; warm start via tail transplant; one variable: history), from
  a stance-basin init; (2) walk-mode park pricing via TIME-AVERAGED
  per-leg load evenness (instantaneous forms can't tell gait from
  park — see cycle 12 routing caution); (3) dense 9-term step
  decomposition stays LAST-resort. Lateral/yaw only after forward is
  real. Rise/lower erosion persists → plan for walk-specialist +
  later merge/distillation.
- **Deployable walk obs:** (1) asymmetric PPO — **CALLED at 8M (cycle
  12): retention tool (rise 11/12 vs nv 3/12, twice), not a gait fix
  (tracking within noise of blind at 4M and 8M). Keep --asym-critic
  for warm continuations.** (2) +history, frame stack vs GRU (~300 ms
  = online system ID) — next; (3) distillation only if those fail.
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

## Queue (in flight → next)

In flight: `cw-stance-posture` (stance champ + k_support_margin 0.3 +
k_load_even 1.5 @ DR 1.0 — fix the lower/rise end-posture defect;
probe-smoked first).

1. Temporal deployable actor (frame stack, env-side history): CODE
   task, then probe, then 4M from a stance-basin init. The gait
   question and the deployable-obs question now share this rung.
2. If cw-stance-posture passes: it becomes the stance champion AND
   the preferred init for the next walk-basin attempt (its posture
   pricing transfers).
3. Mirror-symmetry augmentation (audit MED, queued post-phase-verdict
   — now due) after (1). Contact-from-proprioception aux head after.
   Dense step-decomposition and model-size sweep stay last.

Infra LANDED: canaries + auto-stop, gait-validity gate, end-posture
gate (cycle 12), ledger + watcher dedupe.

## Done =

One policy (or per-skill champion set) that from stance: holds
quietly, lowers/rises on command with randomized timing, walks
forward with real alternating contacts and balanced currents — all
passing visual eval + checkpoint policy + the hardware gate. Then
freeze the candidate and begin supported sim-to-real validation.
