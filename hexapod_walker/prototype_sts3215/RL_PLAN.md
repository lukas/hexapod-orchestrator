# RL Plan — raw-joint policies to hardware candidates

**In plain English:** we're training a walking controller for a real
six-legged robot, in simulation, with an autonomous experiment loop.
The sim robot already walks with all six legs; its feet SLIDE along
the ground while stepping, and that sliding (plus two pending
operator pricing decisions) is what stands between us and putting a
policy on the physical robot. Mission and current status in plain
terms: `rl_docs/GOAL.md`. How to run things: `rl_docs/COMMANDS.md`.

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

Big goal: fluid real-world motion on the physical hexapod — walking
above all. Objective (operator, binding): **DISTANCE, STABILITY,
RELIABILITY** — covers real ground, stays level, never falls. Not
speed-band tracking.

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
   level) + dr.bad_start_prob=0.4 onto the cw-dep contract line as
   soon as vref1-r1/fresh1 have verdicts — every future hardware
   candidate trains with imperfect starts by default. (b) NEW DR AXIS
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

**QUADRUPED** (pulled forward, operator 08-09; authorized parallel
line whenever main-line arms can't fill the pods). Sequence per
readiness review §4, feasibility-first — sweep = GO (c57, 39mm
margin with −20mm shift + splay): quad-hold goal mode **[CODE
LANDED c086a22, 08-09 late — goal mode `quad`, fronts 0+5 via the
goal one-hot, obs width unchanged; spec WISHLIST item 15; probe
clean]** (both fronts clear + unloaded, four planted, level, low
current, 10–15 s hold, 0 term) → weight shift → quadruped stepping.
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
