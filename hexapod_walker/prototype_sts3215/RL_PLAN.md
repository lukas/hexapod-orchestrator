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
  `cw-stance-dr10`) — **posture caveat stands: lower ends flag-leg.**
  Posture pricing (cycle 13) moves near-ground legs only (airborne =
  zero gradient); exploration REFUTED (posture2, cycle 14), which
  also exposed: flat ent 0.01 on a WARM start = std runaway
  (1.0→2.29, 2-for-2 with hist8), skills eroded, flag SPREAD. Warm
  starts keep ent 0.001 + inherited std; entropy RUNAWAY is a health
  alarm alongside collapse. In flight: `cw-stance-endpost`
  (schedule-gated terminal clearance charge, transients untaxed);
  fallback = belly-rest reference states. Flag any eval where
  rise/lower height drops below 5/6; never warm-start stand work
  from an eroded checkpoint.
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
- **Raise: DEMOTED TO CANARY (08-08).** Stuck 2–5/6 everywhere;
  raisemix refuted; failures = near-miss under-lift on ~4 legs. No
  more compute; tripwire only. (Cycle 13: load-even pricing lifted
  raise heights to 11/12 incidentally — still posture 0/12.)
- Seed twins before cw-walk-flag/-s1 were bit-identical clones
  (set_random_seed fix 08-08; earlier twin conclusions discarded).
  Twin eval spread of identical weights (vel_err 0.026 vs 0.043)
  calibrates few-episode eval noise.
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
  curriculum, weak phase-contact reward in both basins (zero-net
  agreement cannot outbid the park's cost savings); **no
  penalty-coefficient iterations, period** (review §0). Rungs:
  (0) operator step-event baseline (queue item 0); (1) **temporal
  actor** (history-8, code landed cycle 13; stance-basin arm
  auto-stopped under-dosed — rerun as one-variable arm on step0);
  (2) walk-mode park pricing via TIME-AVERAGED per-leg load evenness
  (instantaneous forms can't tell gait from park). Lateral/yaw only
  after forward is real. Rise/lower erosion persists → plan for
  walk-specialist + later merge/distillation.
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

- 8 pods on **three ~128-core nodes** (08-08 evening: g142d86 =
  friction/long5m/s3; g129004 = lower/s4/walk; g12ba48 = s5/s6, both
  56-core). The launcher enforces the real budget mechanically:
  `max_heavy_per_node: 2`, experiment cap 6. A 48-env run needs
  ~50–60 cores; more per node starves everything (measured 4-5x).
  Stagger launches; per-run log `/tmp/train_<run>.log`.
- Keep `--eval-every`/`--video-every` ≥200k; periodic eval/video now
  runs in a background worker process (validated 08-08, ~free).
- Pods answer architecture-level questions, not micro reward tweaks;
  multi-seed only after a config wins.

## Queue (in flight → next)

In flight: `cw-walk-h15b-dr03` (0-b rung 0.3 REDO off champion,
long5m) + `cw-walk-step0-hist8` (temporal actor, from scratch, s6).
Finished, verdicts owned by their cycles: `cw-walk-lowent-h15b-c1`
(exploration-vs-structural park), `cw-stance-endpost-c1` (slope rule;
plateau ⇒ belly-rest reference states). **Cycle 20:** `cw-walk-
lowent-dr03` was INVALID — long5m ran pre-audit code, the step-event
cfg-sets were silently ignored for 4M steps (RL_LOG cycle 20).
Eval-only result: the lowent gait still passed the DR0.3 gate (gv
12/12, 0 falls) — DR0.3 looks survivable; clean rung redone on h15b.
Infra: launcher now REFUSES launch unless the pod's `.code_sha`
marker (written by `snapshot.sh --sync`) equals local HEAD.
**Cycle 19: h15b (0-b rung 1) FAILED its gate** within noise of
parent (rung redundant for the gate) but det slip −20%, det 5 s
success 0/12→4/6, std anneal resumed (2.08→1.74). **New walk
champion `ppo_goal_cw_walk_lowent_h15b.zip` md5 d0a12a94.** Gate
blocker is ONE failure class: park basin — ~1/6 sto eps freeze in a
hard tripod park from t=0 (det cousin: duty-skew churn); h15b-c1
tested exploration-gated vs structural; structural ⇒ pricing
(ii)/(iii). Walk defects: park basin, skating (reduced), det
tracking partial (overspeed uncharged; step credit scales with
stride). lowent-c1 (cycle 19c): PASS, deltas inside noise —
identical-config segments CLOSED lineage-wide.

0-a. **step0 lineage (compressed; details RL_LOG cycles 14–18).**
   step0 = first genuine six-leg gait (champion superseded by lowent
   cycle 18). c1/c2 identical-config continuations: plateau, std
   runaway, c2 det falls — CLOSED. Warm starts in this lineage use
   ent 0.001 (lowent A/B evidence). Remaining defects in escalation
   order: (i) consolidation DONE (lowent); (ii) skating price vs
   step-event income; (iii) overspeed/tracking — r_prog caps at
   1.25x but nothing charges above-command speed and step credit
   scales with stride; det ignores commands on every checkpoint.
   (ii)/(iii) are pricing work, due after the 0-b rungs.
   **Canary note (operator, 08-09): step0-lineage continuations run
   `--no-canary`** (c1's auto-stop was a false positive protecting a
   skill the lineage never had). Canaries stay ON for every
   multi-skill run; the exemption is lineage-specific.

0-b. **OPERATOR-DIRECTED (binding, 08-09 ~01:05Z): step0-lineage next
   rungs after the current segments (c2, lowent) verdict.** Both are
   one-variable arms off the best step0-lineage checkpoint;
   continue-while-improving (0-a) and `--no-canary` apply.
   1. **LONGER HORIZON first (cheap, diagnostic):**
      `--episode-seconds 15` (default is 5 — at 2–6 cm/s that caps
      episodes at ~10–30 cm and hides slow-accumulating pathologies:
      heading drift, posture wind-up, jitter build-up). Question:
      does the gait SUSTAIN? Gate: ≥40 cm in 15 s, det AND sto, all
      six legs cycling THROUGHOUT, no degradation in the final third
      (frames, not scalars). If the gait dies after a few cycles,
      fix that before robustifying.
   2. **DR LADDER (the sim-to-real path):** successive warm-started
      segments at dr 0.3 → 0.6 → 1.0, ONE rung per segment; gate =
      the same walk gate at that rung's DR; drop back a rung if the
      gait breaks (hist8 showed wide-distribution warm starts destroy
      parent behavior — never jump straight to 1.0). Hardware-ready
      requires the DR 1.0 rung. May run in parallel with (1) on a
      separate pod if capacity allows, both off the same parent.

0-c. **OPERATOR-DIRECTED (binding, 08-09 ~02:10Z): the walk objective
   is DISTANCE, STABILITY, RELIABILITY** — not speed-band tracking.
   Re-aim the step0/lowent lineage at "covers real ground, stays
   level, never falls," one variable per run as always:
   1. **STABILITY first (it's the current failure — tilt_pitch
      terminations and c2's det falls):** price body attitude during
      walk — per-tick charge on |roll|+|pitch| beyond a small
      allowance and/or on tilt RATE, and an explicit terminal charge
      for a fall, so surviving upright outearns a fast stumble. Fix
      the deepest link first per the root-cause rule: if overspeed
      income (0-a defect iii) is what pushes it past its stability
      envelope, price overspeed in the same arm rather than patching
      tilt twice. Gate: 12/12 det+sto zero terminations, max tilt
      meaningfully below the termination threshold, gait_valid.
   2. **DISTANCE second:** shift income from the speed-band kernel
      toward per-episode ground actually covered (r_prog exists;
      consider gating step-event credit on net forward displacement
      so stride-in-place can't collect). Gate on median distance at
      15 s (h15b's horizon), det AND sto, e.g. ≥0.6 m once stable —
      raise as evidence allows.
   3. **RELIABILITY = the 0-b.2 DR ladder** plus consistency: the
      gate is 12/12 (not 5/6) at each DR rung, and distance variance
      across episodes matters — a policy that walks 1 m or falls at
      50/50 is worse than one that walks 0.6 m every time.
   Sequencing: 1 → 2 → 3, each as a one-variable arm off the current
   champion; continue-while-improving and `--no-canary` apply. The
   0-a pricing defects (skating, overspeed) fold INTO these arms
   where they're the root cause instead of waiting "until after 0-b".

0. **OPERATOR-DIRECTED (binding, 08-08 ~23:00Z): the embarrassingly
   narrow walk (suggested name `cw-walk-step0`).** Dedicate one
   experiment slot to a walk-ONLY policy FROM SCRATCH at DR 0:
   `joint_walk` with NO rise/lower/raise in the goal mix, no
   curriculum sophistication, no asymmetric critic (add only if this
   fails and the log argues why), zero multi-task retention concerns.
   The reward must EXPLICITLY pay for a real step: per-leg credit for
   a completed lift → forward swing → touchdown event, with dragging
   (foot translating while loaded) and parking (per-leg contact duty
   pinned near 0 or 1) explicitly unpaid or priced — i.e. the tripod
   park must be worth less than stepping by construction, not by a
   side effect. Audited exploration settings (std 1.0, ent_coef
   0.005–0.01, target_kl 0.02). Step-event reward is a new mechanism:
   probe smoke first per audit §6. GATE (deliberately narrow): from a
   normal stance, move forward 10 cm with ALL SIX legs repeatedly
   cycling lift/swing/touchdown — per-leg duty in ~[0.2, 0.9], ≥2
   swings per leg, no drag, no parked leg — det AND sto, video
   verdict pathology-first. This is a deliberate fresh-init exception
   to the warm-start default and a new-baseline exception to
   one-variable comparisons. Speed targets, DR, and multi-task merge
   come only AFTER this gate passes.

1. Walk rungs after lowent's verdict: branch (a/c) ⇒ attack skating/
   overspeed per 0-a escalation; branch (b: gait was noise-dither) ⇒
   back to walk escalation order. history-8 arm only on a
   consolidated baseline. Stance: if endpost-c1 plateaus (slope rule),
   belly-rest reference states (reset-side) — no more pricing arms.
2. Mirror-symmetry augmentation (audit MED, due) after (1).
   Contact-from-proprioception aux head after. Dense
   step-decomposition and model-size sweep stay last.
3. Stance-line note: the stance flag leg and the walk tripod park are
   the SAME defect (unpriced airborne legs); fixes should be designed
   once and routed per mode, not invented twice.

Infra LANDED: canaries + auto-stop, gait-validity gate, end-posture
gate (cycle 12), ledger + watcher dedupe.

## After Done: party tricks (operator vision, 08-09)

Once walk passes its DR 1.0 reliability gate (0-c.3) AND rise/lower
are retained: **QUADRUPED MODE** — stand and walk on the four rear
legs with the front two raised free, so the fronts can act as claws/
manipulators. This composes existing skills (walk + unload + raise),
but on a trapezoid support polygon instead of a hexagon — a real
stability step that the 0-c pricing (attitude, falls, load evenness)
should transfer to. Curriculum sketch when its turn comes: (a) static
quadruped stance with fronts raised, hold quietly; (b) weight-shift
and balance under DR; (c) quadruped walk. NOT to be started before
the 0-c gates pass — this is the reward for reliability, not a
detour from it. No binding gates yet; design them at kickoff.

## Done =

One policy (or per-skill champion set) that from stance: holds
quietly, lowers/rises on command with randomized timing, walks
forward with real alternating contacts and balanced currents — all
passing visual eval + checkpoint policy + the hardware gate. Then
freeze the candidate and begin supported sim-to-real validation.
