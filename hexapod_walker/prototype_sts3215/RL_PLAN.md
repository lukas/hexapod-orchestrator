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

## Critical path (simplification review §11, 08-10)

**CURRENT GOAL:** joystick-controlled real robot. **BLOCKERS (as of
08-11 late):** hardware attempt #2 (operator bench — now covers walk,
rot60 off-wedge headings, AND the learned stand-up: the rise+hold
specialist port LANDED 08-11, the runner's stance slot runs
`ppo_goal_cw_stand_holdbc1_hard1` with its trained goal profile
shipped in the weights meta, contract-locked by
`rl_move/tests/test_stand_runner.py`, sim-smoked end-to-end;
stance_dr10 rollback = one picker call). The hold-current "gap" is
RETRACTED (08-11 probe: pose/unit confound; SIM.md gap 2). Rise/hold/lower
and full-circle translation are SOLVED IN SIM; commanded turning is
DE-SCOPED (no camera = no front). **DEFERRED:** quad mode, generic
DR composes, posetrack, architecture curiosity work
not tied to a demonstrated failure. **RULE:** idle GPUs are fine.
**TEST:** the next experiment should take less than one minute to
explain and should change what we do before the next useful
hardware test.

## Where we are (08-11 — live facts in CURRENT_TRUTHS.md)

The real robot walks under a scripted gait — the bar learned policies
must beat. In sim the full joystick cycle now composes with zero
falls (rise → drive any direction via rot60 → stop → sit); turning
is de-scoped. Everything left on the critical path is bench work
(attempt #2: walk + off-wedge headings + learned stand, all staged).

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
- Rise reward-income shaping, reference-tracking-as-crutch, and RSI
  (state-distribution fix) — all beaten by the identical tripod/
  flag-leg cheat. A warp/MJX episode-pool state-loss bug (commit
  65edba7) briefly confounded these closures (score/ref income
  wasn't actually being paid on the GPU path for several arms); the
  fix landed and the clean re-run (`cw-stand-rsi2`, 08-11) reports
  the SAME cheat with mechanism health now verified clean
  (`env/rise_rsi` held ~0.5 all 2M steps, zero corruption) — RE-
  CLOSING all three on stronger evidence. Next lever is CODE only: a
  structural coupling between the height goal and measured foot
  contact (RL_PLAN queue item 2b / rl_docs/RISE.md). Do not propose
  another reward-coefficient or RSI variant on this stack.
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
   park 3.5x under the champion stack. The hold-current inversion is
   RETRACTED (08-11, `probe_hold_current.py`: units ×18 + pose
   confound; sim's proxy overprices 3–25x everywhere, conservative,
   and matches the real walk>hold ordering). DEFERRED, not a
   blocker: a register-scale cmd-fight/deadzone current model —
   prerequisite ONLY for future k_current>0 hardware-pricing arms;
   k_current=0 ruling stands.
2. **Rise/lower inside the walking policy.** Full plan + evidence
   trail: **rl_docs/RISE.md**. Lower is solved warm (rfix-warm1 6/6
   posture-strict; keep fine-tune grafting, distill refuted). Rise:
   six straight reward-income/RSI mechanisms lost to the identical
   flag-leg cheat (CLOSED, see CLOSED moves) — **08-11: the seventh
   lever, a BC anchor OUTSIDE the reward (`cw-stand-bc1`), PASSES**
   (partial): harness-verified honest six-foot plants (bridge 7/12,
   crouch 6/8 valid_plant; flat cold-start 10/10 correct stand,
   footprint-precision-only miss), zero flag-leg cheat in 42 video-
   checked episodes, clean one-variable causal attribution vs the
   identical-minus-anchor parent (still 0/12). Dose-check
   `cw-stand-bc1-coef03` (coef 0.3) **FAILED decisively** (08-11):
   valid_plant 0/16 across every start kind, worse on every axis
   than coef=1.0 — keep `bc_anchor_coef>=1.0`, no more coefficient
   variants. `cw-stand-bc1-hard1` (10M, hardening) **PASSES on rise
   and is the RISE SPECIALIST champion**
   (`ppo_goal_cw_stand_bc1_hard1`): RSI-off probe 12/12 valid_plant
   incl. flat 4/4 (bc1's footprint miss resolved by budget), gate
   det 5/6, feet factor stable all 10M — no re-drift. Dig-in
   matched-parent control (same probe on bc1@2M) refutes the
   "hardening regression" scare: hold/track/raise/lower were ALREADY
   0/12 at 2M (lower flag-leg 166→189mm; raise has p_raise=0 here —
   untrainable). But hold/track splay WORSENS with steps (feet
   51→162mm, 2.6A over-current) — a pre-existing stillness-pricing
   gap amplified, not fixed, by training. Lineage CLOSED for
   hardening; next: hold/track stillness SPECIFICATION (queue 2.3),
   then learned-rise → walk/hold champion handoff composition.
   Detail + numbers: **rl_docs/RISE.md**.
3. **Loaded actuator model.** FIT LANDED 08-10: opt-in
   `--cfg-set bus.servo_params=loaded` (default stays air). Detail +
   provenance + confidence table: **`rl_docs/SIM.md`**. Uncertain
   params (servo reaction times above all) are COVERED BY DR RANGES,
   not exact nominals; hip/yaw are an ASSUMPTION until a per-axis
   loaded ladder. First training arm DONE (08-11 dig-in,
   `cw-dep-vref1-loaded1` PASS): loaded-servo training retains the
   dep-contract walk and slightly beats the air-trained parent under
   matched loaded physics; the ~+40% vel-err/+50% slip vs old
   instant-servo numbers is honest physics (hits the frozen parent
   identically). Loaded params are a viable dep-line training
   default; air-vs-loaded for attempt #2 is a bench decision.
   Remaining: liftoff reproduction on loaded params.
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
    Attempt #2 with `cw-dep-vref1-r1`: fresh set_zero at a known
    visual pose first (a stale/slumped logical stance felled
    a sound scripted gait); deploy tilt trip must match training (25°
    angle + a rate term that trips only when rate is large AND
    carrying the body away from level — never bare gyro magnitude);
    fresh set_zero → plant start; k_current=0. During a scripted-gait
    session: measure walk distance (tape) → unlocks open problem 1.
    Audit sim wz sign vs hardware (+omega = clockwise, measured
    08-09).
0.  **UNIFIED JOYSTICK POLICY (top deliverable).** Stand/sit/turn/
    walk in one checkpoint. Turning: yawcmd/yawgate1/yawgate2 all
    FAILED (fixed left-yaw drift; price tuning CLOSED). The
    signed-income/drift-charge/turn-curriculum mechanism set passed
    its TURN bank but ALSO FAILED to move a real policy
    (`cw-walk-turnfix1`, 08-10: matched-parent control statistically
    identical to the failed parent) — reward-shape tuning on this
    task is now doubly closed. Root-cause reading: the drift is
    baked into the asymmetric WALK GAIT itself, not the turn
    reward's shape/price. NEXT (the only untried lever): mirror-
    symmetry augmentation [CODE — trainer surgery]. Design, bank
    numbers, sign audit, failure detail: **rl_docs/TURN.md**. Measure
    via rl_move/sim/eval_yaw.py + matched-parent control. Rise:
    problem 2. Quad is a MAINLINE joystick command (drive_policy key
    `4`).
    Line gate: joystick-gate retention AND rise/lower ≥5/6 AND quiet
    hold AND clean video on the post-273ebde floor.
0.5 **TEMPORAL-ARCH** (1–2 pods; see Architecture).
1.  Live truth for what's training/queued: `ops.sh census` +
    `launch_run.py backlog list` — never this file.
2.  [CODE] backlog, in priority order:
    1. **Omni translation — RESOLVED IN SIM 08-11 by rot-60 exact
       equivariance (`rl_move/sim/rot60.py`), zero training.** After
       the income re-probe exonerated pricing (honest gait out-earns
       every degenerate 2-4x; collapsed ckpts earn below a freeze —
       optimization failure, not a paid basin) and the 4th collapse
       (`cw-omni-transbc1`, BC anchor on walk ticks) closed
       reward/anchor tuning, the reserve lever landed: the robot is a
       regular hexagon (six identical leg templates at exact 60 deg
       spacing, axisymmetric chassis inertia), so rotate-60+relabel-
       legs is an EXACT model symmetry (test_rot60.py proves it on
       the compiled model, <1e-6 over 30 contact steps). rot60.py
       canonicalizes any heading into the +/-30 deg wedge at eval
       time (obs rotation + leg relabel, action un-relabel).
       Full-circle results, matched naked controls (`logs/rot60/`):
       `cw-dep-vref1-r1` (THE hardware ckpt) naked backward is frozen
       (0.027 m) — wrapped, every direction 0.024-0.036 trk_err at
       DR0 + own DR0.35, zero falls incl. flip stress, harness 20/24
       success, slip/m 1.1-1.3 (own band), video-clean gait;
       hist16-dep1 naked DEGENERATES AT EVAL into the leg-sacrifice
       (slip 7-11/m) — wrapped: gait_valid 24/24, slip 1.3-1.6.
       No omni training arm is needed. **Deploy-side port LANDED
       08-11**: the runner wraps rot60.Rot60Policy itself (no ported
       copy; `rl_policy.py make_walk_canonicalizer`, shipped by
       deploy_adb.sh, default-ON with bit-exact k=0 no-op + off-wedge
       refusal fallback + per-tick `rot60_k` CSV logging);
       replay-parity locked by `rl_move/tests/test_rot60_runner.py`.
       Remaining: BENCH validation during attempt #2 (detail:
       `rl_docs/TURN.md` tail). Eval-side: `eval_drive --rot60`,
       `eval_checkpoint --rot60`.
    2. **Rise beyond income shaping — RESOLVED to a validated
       mechanism 08-11 (BC anchor, lever (a)); the follow-up
       revealed a SEPARATE, pre-existing hold/track pricing gap.**
       Six reward-side arms collapsed to the identical feet-factor
       curve regardless of mechanism (warm-start OOD drift). Lever
       (a) (`rl_move/sim/bc_anchor.py`) landed; `cw-stand-bc1`
       PASSES (partial): harness-verified honest six-foot plants
       (bridge 7/12, crouch 6/8 valid_plant; flat cold-start 10/10
       correct stand, footprint-only miss), zero flag-leg cheat in
       42 video-checked episodes, clean one-variable attribution vs
       the identical-minus-anchor parent (still 0/12). Dose-check
       `cw-stand-bc1-coef03` (coef 0.3) FAILED decisively (valid_plant
       0/16) — keep coef>=1.0. Hardening `cw-stand-bc1-hard1` (10M)
       PASSES on rise (valid_plant 5/6 det, 83%, consolidates with
       budget) but its per-episode duty_cycle/swing_count data expose
       a REAL, pre-existing hold/track stillness gap (legs cycling
       continuously, not the anchor's fault per se — present already
       at 2M, WORSENS with more steps: 12-50mm foot elevation at 2M
       -> 100-161mm at 10M). Do NOT queue another rise
       reward-coefficient/RSI/dose/step-count variant on this
       lineage. Detail: rl_docs/RISE.md.
    3. **Hold/track stillness pricing — SOLVED 08-11 (third lever:
       extending the rise BC-anchor to hold/track ticks).** Two
       pricing-only levers (hard no-flag zero, then a fade) FAILED
       first (0/12 each — earning near-zero reward gave PPO no
       gradient telling a parked leg which way to move).
       `cw-stand-holdbc1` (BC-anchor now also targets hold/track
       ticks) PASSES: harness hold 12/12 valid_plant det+sto,
       worst-foot 2-13mm, video-confirmed level motionless six-foot
       stand det AND sto — first genuine quiet hold in the campaign.
       `env/hold_feet_factor` cleared the 0.1-0.35 plateau to ~1.0 by
       500k steps, held all 2M. Rise retention mostly clean (bridge
       2/2 det, sto 6/6) but det crouch shows 2/6 tilt_roll falls —
       verified against holdstill1 (0 falls)/holdstill2 (1 identical
       fall) as the SAME pre-existing crouch fragility, not new.
       Checkpoint `ppo_goal_cw_stand_holdbc1` (SKILLS.md).
       **Hardening continuation `cw-stand-holdbc1-hard1` (10M)
       PASSES 08-11**: hold valid_plant 11/12 (matches discovery's
       12/12, no regression), `env/hold_feet_factor` held 0.99-1.0
       all 10M, det crouch-start rise improved 2/6->2/4 (33%->50%),
       zero flag-leg/tripod cheat in 24 video-checked episodes.
       `ppo_goal_cw_stand_holdbc1_hard1` is the hardened HOLD+RISE
       checkpoint (SKILLS.md); lineage CLOSED for further hardening.
       **BOTH handoff composition tests DONE + PASS (08-11,
       `eval_handoff.py` / `eval_handoff_reverse.py`): the full sim
       joystick motion cycle composes with zero falls** — specialist
       rise → walk champion on the exact final state (12/12, no
       scripted blend, air AND loaded), and walk → stop → sit
       (specialist lower on the walker's stopped state == its own
       clean band 4/6 posture-strict, only miss a cosmetic 62–99mm
       dangling foot; the scripted go_zero-sit glide is 6/6 both
       physics and covers the deliverable). Crouch rises still tip
       pre-handoff (known fragility; flat+bridge 12/12). Optional
       unqueued polish: BC anchor on lower ticks. rl_docs/RISE.md.
       **Deploy-side port LANDED 08-11 late** (RISE.md tail): the
       runner's stance slot runs the specialist, goal profile rides
       in the weights meta, test_stand_runner.py locks the contract,
       sim smoke green — remaining work is BENCH-ONLY.
    4. explicit mode/command one-hot in the obs (flagship
       prerequisite); LOWER + TURN + WALK trajectory banks for
       test_task_semantics.py (launch blockers for those modes);
       machine-readable metric semantics registry (RESEARCH_RULES);
       contact-from-proprioception aux head; zero-drift DR mechanism
       rework (open problem 5).

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
