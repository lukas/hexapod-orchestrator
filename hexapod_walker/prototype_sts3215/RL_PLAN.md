# RL Plan — joystick-driven hexapod, sim to real

## GOAL (operator, binding — rewritten 08-10, supersedes all prior)

**Drive the real hexapod around with a joystick.** One deployed
policy (or a small blended set) on the physical robot that can
STAND UP, SIT DOWN, TURN, and WALK where the joystick points —
reliably, session after session. Once that works, the party tricks:
lift the front legs and stand on four, then walk on four.

What "good" means: covers real ground, stays level, never falls,
never cooks a motor — reliability over speed. **Foot slip is NOT
failure by itself**: the scripted gait that actually walks the robot
slips visibly (measured 08-09, "maybe helping"). Slip metrics exist
to make sim predictive of the real floor (contact pricing
calibration), not as a ban. Speed-band tracking and zero-slip gates
are means, never the objective.

Pointers: plain-terms mission/status `rl_docs/GOAL.md` · how to run
things `rl_docs/COMMANDS.md` · campaign history `RL_LOG.md` ·
per-run facts `rl_docs/runs/` · full text of every ruling summarized
here lives in `archive/` (this file states only what currently
binds). **EDIT RULE (operator, 08-10): keep this file under ~250
lines and in plain language. New material goes to `rl_docs/` with a
pointer here; superseded detail moves to `archive/` — never
accumulates here.**

## Where we are (plain English — operator + agent, 08-10 morning)

The real robot walks today under a scripted gait (forward, crab,
turns, from a clean zero) — that is the bar learned policies must
beat. In sim the learned gait is real (six legs cycling) but low and
creeping, because sim ground contact prices sliding as free; fixing
that needs one hardware measurement (walk distance, tape measure)
and an operator pricing ruling. The joystick DRIVING stack in sim is
strong and seed-confirmed (±90° steering, latency, friction,
payload, deadband, slopes, 60 s endurance — 0 falls); turn-in-place
(yaw command) and the four-leg trick are trained and under review.
Still failing: stand-up/sit-down inside the same policy as walking
(every reward mix refuted — root cause found, fix arms in flight),
and the stance policy's stand-up collapses at belly-liftoff on
hardware (loaded servos ~5x slower than the air-fitted sim model;
fit in progress). Hardware attempt #2 checkpoint `cw-dep-vref1-r1`
(trained on the exact deployed obs contract) is validated, hardened
against 8 DR axes overnight, pulled to the operator Mac — waiting on
bench time. Launches are on operator hold this morning; analysis
continues.

## Standing rules (binding)

Designing runs:

- One variable per run, off the relevant line's champion.
  Pre-register the gate and BOTH outcomes (if-true / if-false)
  before launch. Two misses in a row = change the hypothesis, not
  the step count.
- New mechanisms get a probe smoke (150k–1M) before a full arm;
  reward changes get a scale audit.
- Warm starts: ent 0.001, inherited std, `--asym-critic`;
  `--no-canary` on single-skill lineages, canaries ON for
  multi-skill. From scratch: std 1.0, ent 0.005–0.01,
  target_kl 0.02. A climbing std is a health alarm.

Judging runs:

- Video is the promotion standard. Name pathologies bluntly (flag
  leg, dragging, skating, jitter, march-in-place). A checkpoint that
  scores well but looks wrong means the METRIC is the bug. ≥12
  episodes (det+sto), at DR 0 AND the run's own DR, 15 s horizon.
- Driving-line runs must pass the JOYSTICK GATE (`eval_drive`:
  0 falls across the direction panel + flip stress).
- Hardware candidates additionally pass Gate 0 (below). Promotion
  criterion (operator): "closest to deployed on the real robot that
  I can joystick reliably" — judged on physical metrics (distance,
  zero falls, attitude, loaded slip/m, per-servo current), never on
  one reward scalar.

Reward routing:

- GLOBAL terms = safety/limits/smoothness only; everything else is
  mode-specific. Income must make doing-nothing (parking, freezing,
  hovering) worth less than the skill BY CONSTRUCTION — audit it,
  don't assume it (the walk park attractor and the rise/lower
  freeze plateau were both this bug).

Process:

- Launches only via `launch_run.py` (capacity, code-SHA gate,
  ledger). Ledger edits only via `launch_run.py update`. One RL_LOG
  line per cycle via `ops.sh logline`.
- When launching is allowed, keep GPU slots busy: a design question
  with a plausible answer never idles a pod — adopt it, log
  "## ASSUMPTION (operator to review)", launch. (08-10 morning:
  operator LAUNCH_HOLD is in effect — analysis only; idle pods are
  expected and correct until it clears.)

CLOSED moves — do not re-propose (evidence in `rl_docs/runs/`):

- Anti-slip / income reward shaping against skating (10+ arms;
  root cause is contact pricing, an operator calibration).
- Identical-config continuations (0-for-5; auto-continue handles
  segment stitching).
- Generic full-DR (1.0) retrains; single-axis calibration/sensor DR
  exposure (13-for-13 no-effect); speed-band arms (gait-limited).
- Raising the slew clamp and retrying a champion.
- posetrack step-extensions (needs a dense curriculum or stays
  parked — not on the joystick critical path).

## Architecture

Settled core: 18 joint-position targets through the SafetyLayer;
actor sees deployable obs only; asymmetric critic; 8-frame history
MLP.

Active exception (operator directive): the TEMPORAL-ARCH line keeps
1–2 pods. hist16 passed its first gate 08-10 (walks from scratch,
joystick gate clean). Next rungs: head-to-head vs the 8-frame
baseline on the deployment contract, then 24 frames, capacity
control, recurrent [CODE].

Not defaults: velocity estimator / DreamWaQ (ruled NOT needed for
hardware attempt #2 — vref1-r1 showed zero erosion under meas:=ref;
revisit only on a demonstrated hidden-state failure).
Transformers/CPG only if the archive review's triggers fire.
Specialist heads / skill conditioning ARE acceptable if that is what
reliable joystick control takes — deployability beats architectural
purity (GPT ruling, 08-10).

## Champions (append-only) + open problems

- **Hardware base: `cw-dep-vref1-r1`** (deployment-exact obs, 25°
  tilt; PASS with zero erosion; hardened vs 8 DR axes 08-10; md5
  f9a466cf) — THE attempt-#2 checkpoint.
- Walk: `ppo_goal_cw_walk_longdist_r2` (md5 bcddc65c). Driving:
  joylat25 → joyfric/joyheadfric family (±90°, latency, friction,
  payload, deadband, slope, 60 s — seed-confirmed, joystick gate
  clean). Stance: `stance_dr10` (heights at DR 1.0; crown jewels,
  canary-protected).

Open problems, in priority order:

1. **Sim contact/current pricing makes creep optimal.** Operator
   calibration; needs the tape-measure walk distance. Fit scripted-
   gait replays on trajectories/timing/tilt/current; contact must
   permit loaded slide; static vs dynamic friction if plain Coulomb
   can't match. Walking measured CHEAPER than standing (0.33–0.45 A
   vs 0.59 A) — sim effort pricing is inverted; k_current=0 on
   hardware arms until calibrated.
2. **Rise/lower inside the walking policy.** Root cause found 08-10:
   warm-start lineage is height_ref-blind AND freezing was paid
   (+120/ep, arrival-gate sign bug). Fix landed (69e00c0):
   `reward.rise_finish_gate_signed=1` + `rise_income_prog_gate=1` —
   ALL future rise/lower arms set both. In flight: cw-uni-rfix-warm1
   vs -fresh1; warm fails + fresh passes ⇒ unified deliverable goes
   distill/two-policy instead of fine-tune grafting (branches
   pre-registered). Rise/lower checkpoints from before sim fix
   273ebde (leg-floor collision) are invalid near the ground.
3. **Loaded actuator model.** FIT LANDED 08-10 (RL_LOG "loaded
   actuator ID"): `fit_loaded_actuator.py` → `sim_model_loaded.json`,
   opt-in `--cfg-set bus.servo_params=loaded` (default stays air,
   legacy-exact). Knee fit from `step_ladder_20260810.csv`: the air
   deadband 0.494° was the sim tracking floor (loaded 0.06°); latency
   85 ms, vel ceiling 48.5°/s, kp 916. Held-out ±5° steps 20–40×
   better than air; rl_stand deployed replay RMSE 2.5° vs 2.9–3.2°.
   Hip/yaw carry knee deltas — ASSUMPTION until a per-axis loaded
   ladder (HARDWARE.md item 4). NEXT: re-run the liftoff reproduction
   on loaded params; first training arm = a dep-line respec with the
   flag vs its air twin.
4. **Quad-mix erosion.** Dose-response so far: 50% erodes walk, 30%
   recovers on the walk champion, 30% on the driving champion
   FAILED, 15% in review. If erosion persists at useful mixes:
   walk-mode KL/distillation anchor to the frozen champion.
5. **Start variation.** The startvar compose FAILED both seeds;
   isolation (noZD1/noBS1, 08-10) shows zero-drift-frame DR is the
   dominant culprit with bad-start interactions — rework the
   mechanism before re-composing. Varied-start eval panel stays
   mandatory for hardware candidates; walk episodes should sometimes
   start from park-bank/slumped poses.

## Queue

-1. **HARDWARE (operator bench — the true critical path).**
    Attempt #2 with `cw-dep-vref1-r1`: deploy tilt trip must match
    training (25° angle + a rate term that trips only when rate is
    large AND carrying the body away from level — never bare gyro
    magnitude); fresh set_zero → plant start; k_current=0. During a
    scripted-gait session: measure walk distance (tape) → unlocks
    open problem 1. Audit sim wz sign vs hardware (+omega =
    clockwise, measured 08-09).
0.  **UNIFIED JOYSTICK POLICY (top deliverable).** Stand/sit/turn/
    walk in one checkpoint. In flight: the rise/lower pricing-fix
    arms (open problem 2). Yaw-rate command channel landed [CODE
    c086a22]; yawcmd1 (+seed) under review. Quad is a MAINLINE
    joystick command (drive_policy key `4`), not a side trick.
    Line gate: joystick-gate retention AND rise/lower ≥5/6 AND quiet
    hold AND clean video on the post-273ebde floor.
0.5 **TEMPORAL-ARCH** (1–2 pods; see Architecture).
1.  Live truth for what's training/queued: `ops.sh census` +
    `launch_run.py backlog list` — never this file.
2.  [CODE] backlog: mirror-symmetry augmentation; contact-from-
    proprioception aux head; zero-drift DR mechanism rework (open
    problem 5).

## Gate 0 — deployment equivalence (every hardware candidate)

Exact controller rate + action map + STATEFUL slew in training AND
eval; deployment-exact obs (meas:=ref); prev-action = raw proposal
(audited PASS 08-10 — don't re-audit); measured actuator dynamics;
25° tilt envelope consistent train/deploy; varied-start panel
(placement + bad-start + zero-drift); zero-command settle / ramp /
stop-restart panels; liftoff-reproduction check; scripted-gait
plant-calibration check whenever sim params change; per-tick
proposed/applied/measured logs. DR passes alone NEVER promote to
hardware. Supported ladder (readiness review): calibrate → retrain
forward gait under corrected physics → freeze on physical metrics →
supported hardware attempt; first milestone is FORWARD joystick, not
omni.

## Still-binding rulings (full text in `archive/`)

- Loaded slip accumulates episode-long (loaded foot-XY travel per
  meter), never reset by touchdown.
- progress_ratio vs commanded displacement (pass 0.75–1.25) replaced
  the 0.40 m gate; reference-relative end-state error replaced the
  60 mm allowance; under-reference is not free.
- support_margin is a stability backstop only; a six-foot end state
  must out-earn any hover. Stance current-economy arms stay blocked
  until the pricing calibration.
- Rear hemisphere deferred; heading ladder frozen at ±90°.
- Promotion = multi-seed panels + named corners; fixed panels are
  regression canaries only.
- Fall recovery waits for the unified policy (orientation-complete
  obs + fallen-pose resets + hard current pricing — quiet
  self-righting; 08-06 incident).

## Done =

The operator picks up the joystick and drives the real robot: it
stands up, walks where pointed, turns, stops, sits down — session
after session, no falls, no hot motors. Then the tricks: four-leg
stance, then four-leg walking.
