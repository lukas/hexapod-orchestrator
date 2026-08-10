# RL Plan — raw-joint policies to hardware candidates

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

Plain-terms mission + status: `rl_docs/GOAL.md`. How to run things:
`rl_docs/COMMANDS.md`.

Rev 2026-08-09d (condensed). Full previous plan with all evidence
inline: `archive/RL_PLAN_FULL_2026-08-09.md`. Campaign history:
`RL_LOG.md` (condensed) → `archive/RL_LOG_FULL_2026-08-09.md`.
Binding reviews: `archive/EXTERNAL_REVIEW_2026-08-08.md` (priority
sequence), `archive/BEST_PRACTICES_AUDIT_2026-08-08.md` (PPO
settings), `archive/ARCHITECTURE_REVIEW_2026-08-09.md` (model
ladder), `archive/OPERATOR_RULINGS_2026-08-09.md` (design rulings).
**EDIT RULE (operator, 08-09 late: budget raised): keep this file
under ~400 lines. Prefer breaking self-contained material into
`rl_docs/` (one topic per doc, pointer here) over inlining; move
superseded detail to archive, don't accumulate it. Hardware evidence
and the experiment backlog live in `rl_docs/HARDWARE.md`.**

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
(every reward mix refuted — root cause under dig-in), and the stance
policy's stand-up collapses at belly-liftoff on hardware (loaded
servos ~5x slower than the air-fitted sim model; fit in progress).
Hardware attempt #2 checkpoint `cw-dep-vref1-r1` (trained on the
exact deployed obs contract) is validated, hardened against 8 DR
axes overnight, pulled to the operator Mac — waiting on bench time.
Launches are on operator hold this morning; analysis continues.

## Standing rules (binding)

- One variable per run, off the current champion; pre-register
  gate + if-true/if-false BEFORE launch. Probe smoke (150k–1M)
  before any new mechanism; reward changes get a scale audit.
- Warm starts: ent 0.001, inherited std, `--asym-critic`,
  `--no-canary` on walk-only lineages; canaries ON for multi-skill.
  From-scratch: std 1.0, ent 0.005–0.01, target_kl 0.02. Entropy
  runaway (std climbing) = health alarm.
- Identical-config continuations are CLOSED as a move (0-for-5).
  Auto-continue handles segment stitching; the trailing verdict
  cycle can kill it.
- Video eval is the promotion standard; verdicts pathology-first
  with explicit hardware-ready yes/no. A checkpoint that scores
  well but looks wrong means the metric is the bug. ≥12 eps
  (det+sto), eval at DR 0 AND the run's own DR, 15 s horizon.
  Exploit-watch columns: cadence/stance count, per-leg swing
  asymmetry, allowance-riding, unload-sweep, flag leg.
- Reward routing: GLOBAL = safety/limits/current/smoothness only;
  everything else MODE-SPECIFIC. Walk income terms must make
  parking worth less than stepping BY CONSTRUCTION.
- Launches only via `launch_run.py` (capacity, code-SHA gate,
  ledger). Ledger edits only via `launch_run.py update`.
- When nodes are free and multiple sound one-variable arms exist,
  launch them in parallel — idle pods during deliberation is a
  failure mode.
- ASSUME AND GO (operator, 08-09): a design question with a
  plausible recommendation never idles a pod — adopt it, log
  "## ASSUMPTION (operator to review)", launch. Operator-ONLY
  blockers (hardware) ⇒ idle pods pick up parallel lines (guardrails
  `operator_unblock_policy`): command-steering, QUADRUPED MODE
  (pulled forward), mirror-symmetry, contact-aux head.

## Architecture (settled — do not propose arms outside this)

18 joint targets through SafetyLayer; deployable-only actor obs;
asymmetric critic; 8-frame history MLP. Next rung (post-0-c):
DreamWaQ-style concurrent estimator. NO transformers/CPG unless
the archive review's triggers fire.

## State + current defects (walk)

- **CHAMPION: `ppo_goal_cw_walk_longdist_r2.zip` md5 bcddc65c**
  (30s/narrow-band lineage; DR1.0 det slip 1.06, seed-confirmed by
  longdist-s1 at 0.98; slip ≤1.0 gate still unmet; NOT
  hardware-ready; joystick gate PASS @DR0.2 AND 0.5, 0 falls incl.
  flips; rare fixed-draw sto stalls = canary only since c52).
  Prior: anchorgate 35234ddc (1.240).
- The gait is real (six legs cycling) but transports by **paddling**
  — the sim's optimum under current pricing (cycle 33). Every income
  lever is exhausted (anchor gate −20% then price ceiling, cycle 34);
  **slip root = contact/current pricing = OPERATOR ruling class.**
- Open defects: skating/paddling (contact/current pricing — the
  hardware calibration data now EXISTS, see Queue -1); overspeed +
  rear-hemisphere RULED.
- DR ladder: CLOSED as vacuous; re-open only if a gait change
  breaks a DR level the parent passed.
- Stance: heights solved at DR 1.0. Lower line UNBLOCKED for gate +
  support_margin rework per rulings; current-economy arms blocked
  until operator hardware calibration. Raise: canary only.

## Queue

-1. **HARDWARE SIM2REAL FINDINGS (operator session 08-09 night —
   HIGHEST PRIORITY, ahead of everything below).** Champion
   longdist_r2 ran twice on the real robot; 25 Hz episode traces +
   fitted motor model are IN THE REPO at
   `rl_move/hardware_traces/` (format: rl_move/API.md § "RL episode
   logging"; robot originals in `linux_control/logs/`). Measured:
   (a) **Deployment-pipeline mismatch dominates.** The on-robot
   SafetyLayer clamps commands to 1.5°/tick; the champion requested
   mean 13°/tick (p95 77°) — **97% of joint-ticks saturated**, mean
   48° proposed-vs-commanded gap: the policy runs ~9× slow-motion
   dynamics it never trained in. ACTION [CODE]: hardware lineages
   train THROUGH the SafetyLayer rate clamp, with walk obs
   vx/vy_meas := ref (board has no velocity estimate); and a
   **mandatory "deployment-pipeline eval"** (clamp + meas:=ref at
   gate time) for any hardware candidate — today's champion fails
   it in sim, which would have predicted the hardware result.
   (b) **Contact/current calibration data now exists** — per-servo
   current every tick in the traces, `logs/motor_model.json` from
   the dynamics probe, and the real floor (rough concrete + rubber
   tips) does NOT let feet slide: attempt 1 turned paddle strokes
   into body roll, −1°→+9° in 1.8 s → tilt_roll trip at 10°. This
   feeds the P0 contact/current pricing calibration (readiness
   review) — that ruling is now actionable.
   (c) Smaller: terminate training at 10° relative roll (= the
   hardware trip); add small random horizontal-force DR (power
   tether tug, visible in the roll direction on video).
   Attempt 2 carried no policy signal (phantom over-temp from a
   corrupted bus byte tripped at 1.1 s; debounced on-robot 08-09).
   Full evidence + the prioritized OPERATOR EXPERIMENT BACKLOG
   (scripted-gait ground truth, hover-vs-planted current, μ
   measurement, loaded step response, latency):
   `rl_docs/HARDWARE.md`.
   **BINDING external review of the walk attempt:
   `archive/GPT_HARDWARE_HANDOFF_2026-08-09.md` (GPT, 08-09).**
   HARDWARE TRANSFER RULING: first walk failed BEFORE gait transfer
   was tested (97% ticks slew-saturated, 48° mean proposed→applied
   gap, zero-command marching, high-grip contact). Broad six-leg
   reward/DR search PAUSED as P0. No policy reaches hardware without
   **Deployment Equivalence Gate 0**: exact controller rate, action
   map, STATEFUL slew/saturation in training AND eval, measured
   actuator dynamics/latency, actor-visible obs only, explicit
   prev-action semantics (raw proposal vs post-safety applied),
   10° relative-tilt termination, zero-command settle + ramp +
   stop/restart panels, per-tick proposed/applied/measured logs.
   Zero-command behavior is a SEPARATE experiment (export/obs audit
   first: captured tick-0 obs through exported MLP vs training net,
   require numerical agreement). Rate clamp: MEASURE loaded
   closed-loop response, then train with the measured stateful
   limiter + modest randomization — do NOT pick a clamp from
   principle, and the backlog's "raised-clamp retry" is WITHDRAWN
   (memo §12: never simply raise the clamp and retry the champion).
   Actuator model build: simple identified first (delay + stateful
   slew + deadband + 1st/2nd-order response + load/voltage limits);
   learned residual only if held-out multi-step prediction demands.
   Anti-slip reward shaping stays CLOSED absent new physical
   evidence.
   **SESSION 08-09 NIGHT MEASUREMENTS (operator; RL_LOG session 3 —
   these BIND the contract arms):** (a) POST-MORTEM CORRECTION: the
   1.5°/tick clamp WAS in raw-joint training (config
   safety.max_delta_q_deg=1.5 + SafetyLayer in sim step path) — the
   "slew limiter is hardware-only" causal rank #1 is refuted as
   stated; remaining contract gaps = walk velocity obs (hardware
   feeds meas:=ref → train with NEW `goal.walk_obs_body_vel=2`),
   tilt envelope, prev-action semantics, contact/current pricing.
   (b) The scripted tripod gait WALKS (fwd/crab/turns) and a WORKING
   gait rocks ±10-20° roll/pitch — 10° tilt termination forbids real
   weight transfer; walk-mode arms train AND deploy with ~25°
   relative-tilt trip. (c) Walking (0.33-0.45 A total) is CHEAPER
   than standing hold (0.59 A) on real hardware — recalibrate sim
   current pricing against `hardware_traces/hw_session2_20260810.csv`.
   (d) Loaded actuator: cmd→motion 110-210 ms, t90 260-430 ms
   (step_ladder trace) — feed the actuator-ID fit. (e) +omega =
   CLOCKWISE on hardware; audit sim wz sign.    (f) Real feet DO slide
   under load in a working gait (operator-confirmed) — contact model
   must permit loaded slide; "floor does not skate" applies to
   body-roll coupling, not micro-slip. (g) Walk ground-truth distance
   NOT yet measured — next operator session, tape measure.
   START-VARIATION ROBUSTNESS (operator directive 08-10 00:38 —
   binding): tonight's scripted-gait falls were caused by stale
   stance + drifted logical zero, NOT by the gait. The operator's
   chosen fix is robustness through variation, not sequencing guards:
   (a) COMPOSE dr.placement_noise_deg=6.0 (the placementnoise6 PASS
   level) + dr.bad_start_prob=0.4 onto the cw-dep contract line —
   `cw-dep-startvar1-r1` + seed twin `-s1` BOTH FAIL HARD (07:0x):
   real sacrificed-leg episode, slip/m up to 22, reward DECLINING
   through training — do NOT use as the hardware base; fall back to
   `cw-dep-vref1-r1`. Two parallel one-axis-removed isolation arms
   running (`-noZD1` zero-drift off, `-noBS1` bad-start off) to find
   the culprit. (b) NEW DR AXIS
   [CODE]: logical-zero drift — an OBS-SIDE per-joint encoder offset
   (the sensors lie consistently by a few deg, e.g. set_zero done on
   a slumped pose). This is DISTINCT from placement noise (physical
   pose slop with truthful sensors); tonight's falls were the
   lying-sensor kind. Start ±3°, anneal up. (c) EVAL: gates for
   hardware-candidate checkpoints must include a varied-start panel
   (placement noise + bad starts + zero drift at eval time), not
   only pristine-plant starts — a checkpoint that only walks from a
   perfect plant is NOT HARDWARE-READY. (d) Walk episodes should
   sometimes start from park-bank/slumped poses (walk_park_bank
   exists) so "stand into stance then go" is in-distribution.
   GPT HANDOFF 08-10 (binding — `archive/GPT_HANDOFF_2026-08-10.md`;
   operator window: ~8h of fleet time before morning hardware
   trials): P0 order = deployment-contract validation → deterministic
   stance-liftoff reproduction → loaded actuator ID → scripted-gait
   real-to-sim calibration → corrected-policy SUPPORTED hardware
   attempt #2. Broad anti-slip reward search and generic full-DR
   retraining stay CLOSED as primary moves; new pair-composes only
   when they protect a named hardware candidate or deployment corner
   — 12/12 DR passes prove robustness around the sim's
   parameterization, NOT that the nominal sim is physically right.
   Rulings: (1) verdict cw-dep-vref1-r1/fresh1 BEFORE inventing new
   walk reward arms; treat fresh1 as unusually important — if 25°
   permission + honest velocity obs yields a visibly higher-amplitude
   weight-transfer gait, take the qualitative change seriously even
   if legacy scalars worsen (the campaign may have been optimizing
   "walk, but never execute the body motion real walking needs").
   (2) RESOLVED 08-10: `cw-dep-vref1-r1` PASSED with no erosion
   (own-cfg det/sto slip+vel_err match or beat the parent evaluated
   on the identical config; see its ledger verdict) — velocity
   estimator / temporal actor is NOT a prerequisite for hardware
   attempt #2; contract-exact obs is enough. Estimator/history stays
   a line for demonstrated hidden-state problems, not a default gate.
   (3) Tilt safety: keep wide
   (~25°) angle ceiling AND add a rate term that trips only when
   |roll/pitch rate| is large AND carrying the body away from level —
   never a bare gyro-magnitude trip (legit gaits transfer weight
   fast). (4) Effort economics: demote/remove walk effort+current
   penalties on hardware-target arms until pricing is calibrated from
   hardware traces (support vs swing vs lowering) — do NOT retune
   from aggregate bus-current ratios. (5) Liftoff collapse = the
   project's best system-ID fixture: replay a window around liftoff
   from real q/qdot/IMU/prev-action under the exact contract and find
   the FIRST diverging observable (prime suspect: air-fitted servo
   model, loaded first-motion latency is 110-210 ms). (6) Scripted-
   gait replay calibration starts NOW on q/qdot+IMU+current (match
   trajectories/timing/tilt/current distribution); do NOT fit
   friction from current+tilt alone — distance/slip lands when the
   operator measures; contact model must permit loaded slide, fit
   static vs dynamic friction if simple Coulomb can't match. (7)
   quad-mix erosion = negative transfer, not a bad skill: map the
   dose-response frontier, then walk-mode KL/distillation anchor to
   the frozen champion if erosion persists; specialist heads/skill
   conditioning acceptable — reliable hardware walking beats
   architectural purity. (8) posetrack: STOP extending the same run;
   small-to-large dense curriculum (near-target starts, short holds,
   grouped errors) or park it — not P0 for the hardware ladder. (9)
   Gate 0 adds: exact obs contract (meas:=ref), prev-action semantics
   audit, tilt envelope consistency, varied-start/bad-start/
   zero-drift panel, fresh-reference init panel, scripted-gait
   plant-calibration check on sim-param changes, liftoff-reproduction
   panel. No hardware promotion from DR success alone.
   OVERNIGHT CONTRACT ARMS (launched 08-09 night, operator): 
   `cw-dep-vref1` = walk champion warm-start with
   walk_obs_body_vel=2 (meas:=ref, the exact deployed contract) +
   25° tilt envelope — hypothesis: champion re-anchors to deployable
   obs without walk erosion; `cw-dep-fresh1` = fresh init, same
   contract, log_std 0.0 / ent 0.005 — hypothesis: with rocking
   permitted (25°) and honest velocity obs, a weight-transfer gait
   (not creep) emerges. Gate for BOTH: deployment-pipeline eval +
   video; compare against the scripted-gait hardware envelope
   (±10-20° rock, 0.3-0.5 A, feet allowed to slip).
0. **UNIFIED JOYSTICK POLICY (operator, 08-09 evening — top
   deliverable): ONE checkpoint that stands up, walks/steers, stops,
   sits down from joystick commands.** No per-skill model zoo. Line
   opens with `cw-uni-blend1-r2` (driving champion + goal-mix blend
   walk=0.7/hold=0.1/rise=0.1/lower=0.1); gate = joystick-gate
   retention AND rise/lower >= 5/6 AND quiet hold AND video shows no
   leg-through-floor. Erosion risk → canary/regression rules apply;
   if walk erodes, ladder the mix (0.9 first), don't abandon.
   Details: WISHLIST item -1.
   **STEERING RUNG UNBLOCKED (08-09 late): the yaw-rate command
   channel [CODE] LANDED (c086a22 + 209d9e9, probe clean, obs 73
   via tail-append → `--obs-pad-transplant 1` warm-starts from any
   non-yaw champion). Spec/risks: WISHLIST item 3. First arm:
   champion + walk_yaw_cmd=1 + k_walk_yaw, gate = yaw tracking on
   commanded turns AND heading hold (drift priced) AND forward-walk
   retention.** **SIM FIX 273ebde (08-09 22:xx) is a
   hard prerequisite for this line: before it, femur/tibia/knee-servo
   had no floor collision, so any rise/lower trained pre-fix could
   sweep shins through the ground (blend1 killed for this; the
   chain-standwalksit flail the operator saw was on the broken
   floor). Rise/lower checkpoints predating 273ebde are suspect near
   the ground; walk-only lineages verified unaffected (zero
   shin-floor contacts in champion gait).**
   **RISE/LOWER ROOT-CAUSE + REWARD FIX (operator session 08-10 am —
   why the whole mix ladder walk=.7/.4/.2/.0 was 0-for-4 on
   rise/lower):** (a) every rung warm-started the SAME walk-only
   champion; init was never varied, and that lineage is measurably
   BLIND to height_ref — the only obs channel distinguishing
   rise/lower from zero-velocity walk (dA/d(height_ref) at the
   unused-channel noise floor, 0.22x proprio avg, vs 4.2x for the
   from-scratch stance champion; no mode one-hot exists). (b) The
   pricing had a PAID FREEZE PLATEAU: freezing at start height in a
   lower episode banked ~+120/ep — kernel income plus a finish-gate
   sign bug (legacy `ref >= target` arrival gate is always-open for
   negative targets) — while every imperfect attempt scored BELOW
   freezing. Fix landed 69e00c0, cfg-gated, defaults legacy-exact
   (smoke: default reward stream md5-identical; freeze +120 -> -16
   with flags on): `reward.rise_finish_gate_signed=1` (sign-aware
   arrival gate) + `reward.rise_income_prog_gate=1` (rise/lower
   kernel+finish income x fraction-of-target covered once the ramp
   departs; hold window ungated; penalties never scaled — same
   worth-less-by-construction rule as the walk income terms). ALL
   future rise/lower arms set BOTH flags. In flight (08-10 ~14:00Z):
   `cw-uni-rfix-warm1` (train-0, mix0-r1 respec, pricing-only arm)
   and `cw-uni-rfix-fresh1` (train-1, the MISSING from-scratch
   control: no init, log_std 0 / ent .005 / DR0.2, same env+mix+
   pricing; also re-proves rise on the post-273ebde floor). Warm
   fails + fresh passes => unified deliverable goes
   distill/two-policy, not fine-tune grafting (full decision
   branches pre-registered in both ledger hypotheses).
0.5. **TEMPORAL-ARCH LINE: keep 1-2 GPU pods running it (operator,
   08-09 evening — by directive, not mechanical enforcement).** More
   past states for complicated movements (rise/sit, flips, turns).
   history_frames ladder 8->16->24, then capacity control, then
   recurrent [CODE]. Spec + gates: WISHLIST item -0.5. When you
   refill and no arch run is training anywhere, queue the next rung.
1. **In flight:** never listed here — a static doc can only be
   stale. Live truth: `ops.sh census` (what's training),
   `launch_run.py backlog list` (what's queued),
   `rl_docs/runs/<run>.md` (what each finished run showed).
   Landed verdicts that shape the plan: stepdisp12 + loadslip both
   FAIL/refuted, seed-confirmed → the walk-reward income side is
   CLOSED (slip root = sim contact/current pricing, operator
   calibration class).
2. **0-c objective arms, in order, one variable each:**
   (i) STABILITY: CLOSED as a reward lever — terminal fall charge
   refuted (dr05-fall300, falls too rare for gradient) and tilt
   pricing NO-EFFECT on the champion line (longdist-tilt05 vs
   partner, all deltas inside noise). Full-DR champion retrain
   REFUTED too (longdist-dr10 FAIL c53: no reliability gain,
   nominal erosion) — rides on targeted axes (terrain/payload/
   latency/torque).
   (ii) DISTANCE: LANDED (longdist 30s narrow-band → champion,
   cycle 44). (iii) RELIABILITY: stall front CLOSED c52 — DR
   (longdist-dr05), cmd-resample (stallfix; helps only when resample
   is on at eval), park-bank (0/60 harvest eps → <2% rare tail,
   canary-only) all refuted/unfundable; rides on DR/terrain arms.
3. Mirror-symmetry augmentation (needs its own implementation
   cycle: mirror index maps + trainer support + probe).
4. Contact-from-proprioception aux head; dense step-decomposition
   and model-size sweep last.

OPERATOR RULINGS 2026-08-09 (BINDING — read
`archive/OPERATOR_RULINGS_2026-08-09.md` before stance/gate work):
(1) 60 mm allowance RETIRED → reference-relative end-state error,
interim cap 25–30 mm, under-reference NOT free; (2) support_margin
= stability backstop only — six-foot end state must out-earn any
hover; (3) stance current economics BLOCKED until the operator's
hardware calibration (2.6 A ≈ stall-scale; hardware = OPERATOR-ONLY);
(4) rear hemisphere DEFERRED — gates draw forward/fwd-diag only;
(5) 0.40 m gate RETIRED → progress_ratio vs commanded displacement,
pass 0.75–1.25; prefer narrow forward band + direct distance gate;
(6) loaded slip accumulates episode-long, NEVER reset by touchdown
(loaded foot-XY travel per meter = primary skating metric);
(7) promotion = multi-seed panels + named corners; fixed panel =
regression canary only;
(8) **promotion criterion (operator, 08-09 ~10:3x): "closest to
deployed on the real robot that I can joystick reliably."** Promote
on physical deployability — distance, zero falls, attitude, loaded
slip/m, per-servo current, low safety intervention — NOT on any one
reward metric; det improvement with sto parity is sufficient (the
c44 longdist-r2 promotion is operator-ACCEPTED under this rule).
After reliable joystick walking, the bar becomes tricks (four-leg
stance first).

EXTERNAL READINESS REVIEW 2026-08-09 (operator-supplied, adopted):
`archive/HEXAPOD_READINESS_RESEARCH_REVIEW_2026-08-09.md`. Its
priorities are binding guidance: **P0** = contact/current
calibration → retrain forward gait under corrected physics → freeze
a forward-only policy by physical metrics → supported hardware
ladder (§2 Gate C; first milestone is FORWARD joystick, not omni).
**P1** = four-leg line in parallel on spare GPUs, feasibility FIRST
(§4: scripted CoM/support-polygon/torque sweep with fronts raised —
no reward design until geometry passes). **P2** = joystick envelope
(speed band → diagonals → lateral → yaw → rear) only after forward
transfer. No new anti-slip reward coefficient arms (§8).

## Party tricks (operator vision, 08-09)

**QUADRUPED — PROMOTED TO MAINLINE JOYSTICK COMMAND (operator
08-10 00:4x: "four leg trick in the main line so I can hit that
with the joystick in sim to real").** No longer a side trick: quad
is a commanded behavior of the DRIVING lineage. Mechanism proven by
cw-quad-hold1-r2 (hold works, survived 1.0; 50% mix eroded walk =
the pre-registered if-false branch). Live arms: cw-quad-hold2 (30%
mix on walk champion) and **cw-walk-joyquad30** (30% mix composed
onto driving champion joylat25 with its full DR0.5+latency+flip
spec — THE sim-to-real candidate; gate = joystick gate retained +
quad hold metrics + walk slip in parent band). Operator drives it
today with `drive_policy.py` key `4` (toggles lift_legs=(0,5) live).
Original ladder — quad-hold goal mode **[CODE LANDED c086a22 —
goal mode `quad`, fronts 0+5 via the goal one-hot, obs width
unchanged; spec WISHLIST item 15; probe clean]** (both fronts
clear + unloaded, four planted, level, low current, 10–15 s hold,
0 term) → weight shift → quadruped stepping.
Never ask the six-leg walker to spontaneously stop using two legs.
**FALL RECOVERY** waits for 0-c: fallen poses as start distribution,
gate "regain stance and hold 12/12 under DR"; needs
orientation-complete obs + fallen-pose resets + hard current pricing
(quiet self-righting — 2026-08-06 incident). Full design sketches:
`archive/RL_PLAN_FULL_2026-08-09.md`.

## Done =

One policy (or per-skill champion set) that from stance: holds
quietly, lowers/rises on command, walks forward with real
alternating contacts and balanced currents — passing visual eval +
the hardware-candidate gate (full checklist in the archived plan:
20-ep evals, current limits, noise robustness, frozen-policy mass
eval). Then freeze and begin supported sim-to-real validation.
