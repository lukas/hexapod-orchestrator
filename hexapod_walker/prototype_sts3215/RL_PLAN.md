# RL Plan — joystick-driven hexapod, sim to real

## GOAL (operator, binding — rewritten 08-10, supersedes all prior)

**Drive the real hexapod around with a joystick.** One deployed
policy (or a small blended set) on the physical robot that can
STAND UP, SIT DOWN, TURN, and WALK where the joystick points —
reliably, session after session. Once that works, the party tricks:
lift the front legs and stand on four, then walk on four.

What "good" means: covers real ground, stays level, never falls,
never cooks a motor — reliability over speed. **Foot slip is NOT
failure by itself** (the scripted gait that walks the robot slips
visibly); slip metrics keep sim honest about the real floor, never a
ban. Speed bands and zero-slip gates are means, never the objective.

Startup reading order (operator + GPT, 08-10): `RL_GOALS.md`
(mission) → **`CURRENT_TRUTHS.md`** (accepted facts — outranks any
history file) → this file (blockers/queue/architecture/gates) →
**`RESEARCH_RULES.md`** (binding agent behavior: prime directive,
phases, preflights, kill rules) → `rl_docs/SIM.md`. As needed:
`rl_docs/COMMANDS.md` (how to run things) · `rl_docs/REWARD.md`
(every reward term + per-run reward auto-doc) · `rl_docs/EVALS.md`
(eval metric definitions) · `rl_docs/RISE.md` (stand-up plan) ·
`rl_docs/SKILLS.md` · `rl_docs/runs/` (per-run facts). History (`RL_LOG.md`, `archive/`) only for historical
questions — never to infer current state. **EDIT RULE (operator,
08-10): keep this file under ~250 lines and in plain language. New
material goes to `rl_docs/` with a pointer here; superseded detail
moves to `archive/` — never accumulates here.**

## Prime directive (operator, 08-10 — full text: RESEARCH_RULES.md)

**Minimize the number of unresolved blockers between the current
robot and the next useful hardware joystick test — that count is the
campaign KPI, not GPU occupancy.** Idle pods are acceptable when the
critical path is hardware, specification work, or code fixes. Every
spec answers the launch question first: if this run succeeds or
fails, does it change what we do before the next hardware test?

## Where we are (08-10 — live facts in CURRENT_TRUTHS.md)

The real robot walks under a scripted gait — the bar learned policies
must beat. Sim driving stack: strong, seed-confirmed, joystick-gate
clean. Still failing: commanded turning (structural left-drift; price
tuning closed) and stand-up (every arm loses to the height-only
cheat — see rl_docs/RISE.md). Hardware attempt #2 checkpoint
`cw-dep-vref1-r1` is validated, hardened, pulled to the operator
Mac — waiting on bench time.

## Standing rules → `RESEARCH_RULES.md` (binding; moved 08-10)

How to design, launch, stop, and judge experiments lives in
**`RESEARCH_RULES.md`**: the phase system (SPECIFICATION / DISCOVERY
0.5–2M / HARDENING 10–40M / COMPOSITION / TRANSFER, launcher-
enforced), MDP_PREFLIGHT (`test_task_semantics.py` orderings per
mode), matched-parent controls, behavioral-impossibility kills,
DIG-IN triggers, reward routing, warm-start recipes, and the launch
question ("does this change what we do before the next hardware
test?"). Promotion criterion (operator): "closest to deployed on the
real robot that I can joystick reliably" — physical metrics, never
one reward scalar. Hardware candidates pass Gate 0 (below).

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
- Treating another pairwise DR-compose PASS as progress: the compose
  campaign proved broad robustness; broad robustness is not simulator
  accuracy, and it is not on the blocker list (operator, 08-10).
- Further single/pair/ANY-N-way DR composes on `cw-dep-vref1-r1`
  (the "protect-the-candidate" sweep): CLOSED 08-10 night, 20-for-20
  no-effect — every sensor/actuator/assembly axis tested solo or
  paired composes free with the IDENTICAL benign fixed-eval-seed
  fingerprint (det/4 catastrophic crater at DR0; det/5+sto/0-1 mild
  degradation at own-cfg DR0.35); an all-axes-stacked "megastack" is
  the predictable terminal case of the same closed class, not new
  evidence — do not requeue it under any name (`cw-dep-vref1-r1-
  megastack1` and renamed retries repeatedly pruned 08-10 ~20:35).

## Architecture

Settled core: 18 joint-position targets through the SafetyLayer;
actor sees deployable obs only; asymmetric critic; 8-frame history
MLP.

Temporal ladder PAUSED at hist16 (operator, 08-10): hist16 passed its
first gate (walks from scratch, joystick gate clean) and becomes the
default for the flagship below. No 24-frame / recurrent / transformer
rungs until the flagship answers the real question — "can a
history-aware policy with a correctly specified multitask MDP learn
the joystick skill set?" — not "what is the best temporal arch?".

**FLAGSHIP (queued behind the rise + turn MDP preflights passing):
clean-sheet unified policy.** hist16 + EXPLICIT mode/command one-hot
[CODE — the obs has no mode signal today] + 256×256 (or 256×256×128)
MLP, from scratch, on HOLD/RISE/LOWER/WALK/TURN (not quad). Staged
curriculum, not a fixed mixture: (A) hold + plant + near-plant
rise/lower, (B) expand rise→belly / lower→sit, (C) forward
locomotion, (D) turns, (E) transition-heavy joystick episodes.
Pre-registered outcomes: works → the unified model IS the
deliverable; skills fight → MoE justified (shared hist16 encoder +
~4 small experts); rise cheats again → the MDP is still wrong,
architecture exonerated. This experiment — not the graft lineage —
decides specialists vs one network.

Not defaults: velocity estimator / DreamWaQ (NOT needed for attempt
#2; revisit only on a demonstrated hidden-state failure);
transformers/CPG only on the archive review's triggers. Specialist
heads / skill conditioning ARE acceptable if that is what reliable
joystick control takes — deployability beats purity (GPT, 08-10).

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

1. **Sim contact/current pricing.** Contact HALF-CLOSED (08-10):
   `calibrate_slip.py` replays the exact hardware gait; sim travel
   ratio 0.35–0.41 vs real 0.50–0.51, speed-invariant, walk current
   in-band — sliding is NOT free in sim (slightly conservative), μ
   saturates ≥1.5, XML friction stands (`env.foot_friction_slide`
   hook landed for future floors; SIM.md gap 1). WALK semantics bank
   landed and PASSING: the tape-proven gait out-earns stall 1.9x and
   park 3.5x under the champion stack. REMAINING: effort pricing at
   hold (sim 0.11 A vs real 0.59 A, not scalar-fixable) — fit a
   load-dependent holding-current model on the existing per-servo
   traces; k_current=0 on hardware arms until then.
2. **Rise/lower inside the walking policy.** Full plan + evidence
   trail: **rl_docs/RISE.md**. Lower is solved warm (rfix-warm1 6/6
   posture-strict; keep fine-tune grafting, distill refuted); rise is
   unsolved — every arm incl. `cw-stand-b2p1` lost to the height-only
   flag-leg/tripod cheat under the full stack. The GEOMETRIC stand
   spec is LANDED (08-10): PLANT_SPEC/`valid_plant()` in sim_env.py
   (one criterion for reward gate `rise_plant_polygon_gate`, harness
   report + `--valid-plant-gate`, and the rise bank — replay valid,
   stilt/freeze/partial all fail). Next rise arm trains WITH the
   polygon gate; do not re-run b2p1 with more steps or different
   weights. The rise bank in `test_task_semantics.py` is the binding
   preflight; new mechanisms go through DISCOVERY first. Big
   consolidation waits for the loaded-actuator model.
3. **Loaded actuator model.** FIT LANDED 08-10: opt-in
   `--cfg-set bus.servo_params=loaded` (default stays air). Detail +
   provenance + confidence table: **`rl_docs/SIM.md`**. Uncertain
   params (servo reaction times above all) are COVERED BY DR RANGES,
   not exact nominals; hip/yaw are an ASSUMPTION until a per-axis
   loaded ladder. NEXT: re-run the liftoff reproduction on loaded
   params; first arm = a dep-line respec, loaded vs its air twin.
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
    Attempt #2 with `cw-dep-vref1-r1`: FIRST correct the known
    L5 / leg-zero / trim issue (a stale/slumped logical stance felled
    a sound scripted gait); deploy tilt trip must match training (25°
    angle + a rate term that trips only when rate is large AND
    carrying the body away from level — never bare gyro magnitude);
    fresh set_zero → plant start; k_current=0. During a scripted-gait
    session: measure walk distance (tape) → unlocks open problem 1.
    Audit sim wz sign vs hardware (+omega = clockwise, measured
    08-09).
0.  **UNIFIED JOYSTICK POLICY (top deliverable).** Stand/sit/turn/
    walk in one checkpoint. Turning: yawcmd/yawgate1/yawgate2 all
    FAILED (fixed left-yaw drift; price tuning CLOSED). The new
    mechanism set is LANDED + its TURN bank PASSES (08-10): signed
    rotation income `reward.k_yaw_prog`, heading-hold drift charge
    `reward.k_yaw_still`, turn-in-place curriculum
    `goal.walk_turn_in_place_frac` — design, bank numbers, sign
    audit, and the recommended DISCOVERY arm: **rl_docs/TURN.md**.
    Measure via rl_move/sim/eval_yaw.py + matched-parent control.
    Rise: problem 2. Quad is a MAINLINE joystick command
    (drive_policy key `4`).
    Line gate: joystick-gate retention AND rise/lower ≥5/6 AND quiet
    hold AND clean video on the post-273ebde floor.
0.5 **TEMPORAL-ARCH** (1–2 pods; see Architecture).
1.  Live truth for what's training/queued: `ops.sh census` +
    `launch_run.py backlog list` — never this file.
2.  [CODE] backlog: geometric valid-plant terminal state for rise
    (support-polygon/foot-count success criterion that rejects
    flag-leg/tripod — define AND test it in the rise bank, problem
    2); explicit mode/command one-hot in the obs (flagship
    prerequisite); LOWER + TURN + WALK trajectory banks for
    test_task_semantics.py (launch blockers for those modes);
    machine-readable metric semantics registry (RESEARCH_RULES);
    mirror-symmetry augmentation; contact-from-proprioception aux
    head; zero-drift DR mechanism rework (open problem 5).

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
