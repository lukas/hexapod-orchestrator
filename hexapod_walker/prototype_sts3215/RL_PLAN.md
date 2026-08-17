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

## Research tracks (operator, 08-11 — full rules: RESEARCH_RULES.md)

The campaign runs as PARALLEL TRACKS, each with its own goal, W&B tag
(`track:<id>`), and status doc (`rl_docs/tracks/`). Registry:
`rl_move/orchestrator/tracks.json`. **hw** = joystick robot on
hardware by any means (MAINLINE, pod priority — this file's queue is
mostly hw); **arch** = GRU/temporal models learning walk/stand/sit;
**nobc** = stand + clean gait from scratch, no BC anchor ever;
**quad** = walk on four legs, front pair as hands; **turn** =
commanded yaw via mirror symmetry; **multitask** (opened 08-12,
operator brief; **PAUSED by operator 08-13** — dynrep takes
priority, no `cw-mt-` launches until unpaused) = fresh
command-conditioned generalist — stand + forward + small yaw as ONE
command family, A/B/C specialist-vs-generalist cohort + transfer
test; design + binding
verdict labels: `rl_docs/MULTITASK.md`; **dynrep** (opened 08-12,
operator brief) = self-supervised action-conditioned dynamics
pretraining → frozen/anchored-z PPO transfer; hard baseline gate
before any PPO; design: `rl_docs/DYNREP.md`, code
`rl_move/dynamics/`. Non-hw tracks run on excess
capacity. **Containment: a triaged run's follow-ups stay in its
track; cross-track findings are escalated in writing, and
cross-track launches are operator-only.**

## Prime directive (operator, 08-10 — full text: RESEARCH_RULES.md)

**Minimize the number of unresolved blockers between the current
robot and the next useful hardware joystick test — that count is the
campaign KPI, not GPU occupancy.** (Scope 08-11: this is the hw
track's directive; other tracks substitute their tracks.json goal.)
Idle pods are acceptable when the
critical path is hardware, specification work, or code fixes. Every
spec answers the launch question first: if this run succeeds or
fails, does it change what we do before the next hardware test?

## SIM SPRINT (operator, 08-17 ~18:05 UTC — binding, CURRENT; wins
## over anything below where they disagree)

**The robot is off the bench for about a day of repair. Until the
operator announces it is back, the whole fleet's single deliverable
is RELIABLE RISING + WALKING IN THE MUJOCO SIM, download-ready.**
The operator is confident about downloading a policy onto the robot
as soon as it is fixed — so every cycle answers one question first:
*"if the robot were fixed tomorrow morning, what exactly would we
download?"* Keep that answer concrete: named checkpoints + gate
evidence (SKILLS.md / session-gate numbers), single policy or the
session-controller composition — whichever is genuinely closest.
**The maintained answer lives at `rl_docs/DOWNLOAD_ANSWER.md`
(written 08-17 repivot cycle; update it whenever a verdict changes
it).**

Priority order while the sprint runs:

1. The named reliability gaps on the rise/walk session line — the
   post-lower rise (the one open sim training target), the takeoff
   roll transient, any zero-fall or over-current regression on the
   bulk session gate.
2. Hardening + retention of the rise and walk champions (Gate 0 /
   deployment contract, eval_session, varied starts) so the
   download candidate is export-ready, not a lab result.
3. Anything else ONLY if it directly moves sim rise+walk
   reliability this week.

Research tracks (dynrep, arch, nobc, quad, turn, multitask): no new
launches unless the arm directly serves sim rise+walk reliability;
in-flight runs may finish and be triaged normally. Bench-owned
[operator] queue items stay parked — there is no robot to test on —
and cycles do not steer toward hardware attempts until the operator
says the robot is back.

## Operator directive (08-11 night — binding)

**Make standing and walking work IN SIM, to deployable-champion
quality, and keep the fleet firing at exactly that.** Cycles think
root-cause-deep about the open stand/walk blockers (hold's parked
foot, det flat-rise stall, rise-rock + takeoff roll-rate DR axes,
the crouch-splay tall wall, contact/pinning, and the 08-11
interactive-profile overfit — deployed sit-from-plant tips + rise
stalls under play.py's ramp, MODEL_TOUR) and keep launching arms
that directly attack them — each spec'd so a PASS is a hardware
candidate (Gate 0 / dep contract, champion warm-start, retention
gates), not a throwaway. When the next lever is CODE (several are:
rise-rock DR + bank, takeoff roll-rate injection, BC-INIT
pretraining on the scripted tall gait, physics-easing ladder,
min-over-feet hold pricing + per-mode bc_anchor_loss logging), the
cycle WRITES it and checks it in: new cfg keys, DEFAULT OFF,
bit-exact when off, tests/banks green, snapshot before training —
never blast shared defaults with experimental code, never park a
line on "CODE, unbuilt". Idle pods next to an unattacked stand/walk
blocker are now the failure mode; peripheral runs stay banned.

## Critical path (simplification review §11, 08-10)

**08-14 UPDATE (bulk session gate — supersedes the sim-side stand/
walk blocker ranking below where they disagree):** the hierarchical
specialist pair (footlow2_hard1 + bcgait1_hard1 + session controller
+ entry-slew + STOP→stance-hold) PASSED the pre-registered bulk
held-out session gate (n=600 fresh sessions: det zero-fall 0.967,
sto 0.853 — `rl_docs/tracks/hw/SESSION_BULK_GATE.md`) and is the
measured PRODUCT BASELINE (operator directive
fb_20260814T205137_33f21c); single-policy consolidation is research,
not a blocker. The ONE named sim-side training target left on this
line: the POST-LOWER RISE (all det failures, sto 0.801,
over_current-dominated) — train only that transition/residual with
the skills frozen. Everything else on the joystick line is now
bench-owned ([operator]: candidate-pair promotion, entry-slew flip,
takeoff reps). **FIRST ATTEMPT FAILED (`cw-stand-postlower1`,
Cohort c2, n=600): 35% post-lower start-bank exposure REGRESSED sto
post-lower rise 0.801→0.717 (plus small det/cold-rise/drag hits),
no exploit — genuine over_current stall, just more of it.
`cw-stand-postlower2` (discovery 2M, frac 0.15) running now to
split dose vs a mis-priced rise_ref reference before any further
hardening — `rl_docs/tracks/hw/SESSION_BULK_GATE.md` "Cohort c2".**

**CURRENT GOAL:** joystick-controlled real robot. **BLOCKERS (as of
08-11 late):** the intermittent RUNAWAY ROLL on real ground (RL walk
attempts 08-10: vref1-r1 2/2 runaway, tip1 1 runaway / 3 clean —
queue item -1 has the full state; the discriminating A/B + the sim
contact/pinning question are the open work), plus the FIRST bench
runs of the newly landed pieces: rot60 off-wedge headings and the
learned stand-up (rise+hold specialist port LANDED 08-11, trained
goal profile shipped in the weights meta, contract-locked by
`rl_move/tests/test_stand_runner.py` — needs a deploy re-push
first; stance_dr10 rollback = one picker call). The hold-current
"gap" is RETRACTED (08-11 probe: pose/unit confound; SIM.md gap 2).
Rise/hold/lower and full-circle translation are SOLVED IN SIM —
**but only under the TRAINING goal profiles: the 08-11 model tour
(rl_docs/MODEL_TOUR_2026-08-11.md, all 27 deployable ckpts through
the interactive play.py session) found the deployed stance tips
deterministically on sit-from-the-142mm-plant and stalls its belly
rise at 55 mm under the interactive ramp. New session gate
`rl_move.sim.eval_session` (exit-code enforced; run it on every
stand/sit candidate alongside the mode gates) + new default-off
training axis `goal.rise_ramp_jitter`/`goal.lower_ramp_jitter`
(bank: test_ramp_jitter_* green). First arm: champion-lineage warm
retrain with jitter ~0.3, gate = eval_session hard gates + mode
retention.** **Sanctioned compute
experiment lines (operator 08-11 afternoon — not attempt-#2
blockers, but wanted): turning (RE-OPENED, queue 0.2), four-leg
walking (NEW, queue 0.3), tall/no-drag walking (queue -0.5). All
three are diagnosis-first: audit whether the reward actually pays
the desired behavior before launching arms.** **DEFERRED:** generic
DR composes, posetrack, architecture curiosity work
not tied to a demonstrated failure. **RULE:** idle GPUs are fine.
**TEST:** the next experiment should take less than one minute to
explain and should change what we do before the next useful
hardware test.

## Where we are (08-11 — live facts in CURRENT_TRUTHS.md)

The real robot walks under a scripted gait (tape-measured), and a
learned policy has now driven it too: `dep-tip1` walked level 3 of 4
bench runs 08-10 (vref1-r1 went 0/2 with runaway roll — see queue
-1). In sim the full joystick cycle composes with zero falls (rise →
drive any direction via rot60 → stop → sit); turning is de-scoped.
The critical path is the runaway-roll question (bench A/B + possibly
a sim contact fix) and first bench runs of rot60 + the learned
stand-up.

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
  root cause is contact pricing, an operator calibration). SCOPE
  narrowed 08-11 (operator): this closes income gates/shaping
  retrofitted onto trained paddlers — it does NOT close the GAIT
  CLEANUP line (queue -0.5 / rl_docs/GAIT.md): banked structural
  drag charge, swing clearance, or from-scratch task curricula.
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

**FLAGSHIP (stage A TRAINED 08-11: `cw-uni-flag-a1-r1` 2M +
`-h2` 10M hardening): clean-sheet unified policy.** hist16 +
EXPLICIT mode/command one-hot + 256×256 MLP, from scratch, on
HOLD/RISE/LOWER/WALK/TURN (not quad). Staged curriculum: (A) hold +
near-plant rise/lower, (B) expand rise→belly / lower→sit, (C)
forward locomotion, (D) turns, (E) transition-heavy episodes.
Stage-A result: hold 6/6 + lower 12/12 at specialist grade FROM
SCRATCH (first time), rise (all-crouch) plateaued 1/6 with flat
factors across 10M, NO cheat (honest sprawl-stall/tip-over — the
same crouch fragility the deployed specialist has, 0/6 RSI-off).
None of the pre-registered outcomes fired cleanly; "skills fight →
MoE" needs interference MEASURED, not inferred (no from-scratch
rise-only cell ever ran). **08-11: `cw-uni-flag-a1-risectl1` (2M,
rise-only, one variable, the missing cell) REFUTES the MoE fork.**
Isolated on stand-up alone (zero sibling skills to fight for
capacity, 2.5x the flagship's rise-tick exposure), it lands in the
IDENTICAL band: det valid_plant 1/6 (matches h2's 1/6 exactly),
`env/rise_feet_factor` last-quarter mean 0.537 (flagship band
0.44–0.64, confirm threshold was >0.8), zero exploit fingerprint in
12 video-checked episodes (honest crouch-start tip-overs/sprawl-
stalls, same shape as h2). Shared-capacity interference is NOT the
cause — a network with nothing else to learn hits the same wall.
**Do not build MoE for unified-policy rise.** The bottleneck is
rise-from-scratch itself (matches the deployed BC-anchor specialist
also failing 0/6 RSI-off on crouch starts before its start-mix fix).
Next lever if this line reopens: specialist seeding/warm-start, not
another reward/mix variant — but this is now architecture curiosity,
not a hardware blocker (specialist-handoff composition already
covers rise for attempt #2, deployed 08-11). No further flagship
arms queued this cycle.

Not defaults: velocity estimator / DreamWaQ (NOT needed for attempt
#2; revisit only on a demonstrated hidden-state failure). 08-11 eve
status of that rung: leg-odometry estimator BUILT and unit-tested
(`rl_move/estimator.py`, sim-validated at DR0, corr collapses at
DR0.5) but REFUTED as a hardware velocity source by the operator's
tape data — real feet slip ~50%, and leg odometry over-reads by
exactly the slip fraction (it cannot tell planted from sliding).
Fleet evidence agrees velocity obs is not the gait lever (nv/nv2:
"deployable obs are not the blocker"; aac: retention tool only). If
true body velocity is ever wanted, the honest path is a downward
optical-flow sensor (PMW3901, ~$20, SPI, works ≥80mm height — fits
the ~142mm walk stance), not more inference.
Transformers/CPG only on the archive review's triggers. Specialist
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
    **Attempt #2 HAPPENED (08-10 eve/night — stop calling it
    pending; full findings rl_docs/HARDWARE.md).** `cw-dep-vref1-r1`
    ran twice: runaway roll both times (opposite signs →
    environmental seed; pinned-loaded-leg positive feedback, no
    trained recovery). Its tipped-start retrain `cw-dep-tip1` then
    ran 4x: 1 runaway / **3 CLEAN level walks** — a learned policy
    HAS driven this robot. Obs pipeline proven bit-exact (offline
    replay err 0.0014); sag is the commanded trained posture;
    scraping is the known low-clearance shuffle (→ GAIT queue -0.5).
    Scripted-gait tape: ~50% of commanded (done). STILL OPEN on the
    bench: (a) the vref1-r1 vs tip1 A/B on the same floor (the 08-10
    attempt never actually switched policies — compare roll-ramp
    RATE / runaways per N, not one run); (b) tape reading on an RL
    walk; (c) FIRST hardware runs of the newly-landed rot60 port and
    the stand specialist — **deploy re-push DONE 08-11 ~21:15,
    HTTP-verified: active stance policy is stand_holdbc1_hard1 WITH
    its trained goal profile (stand 5s/6s/+111mm), STAND no longer
    stale**; (d) wz sign audit — **DONE 08-11 night (operator: turns
    match the drawn signs both ways, no bridge flip; rate
    unmeasured)**. If the runaway recurs on tip1 too,
    the fix is a sim contact/pinning model (no-skate feet), not
    more DR. **Session runner: `rl_move/scripts/bench_blast.py --go`
    (guided checklist, all of a-d); sim half `rl_move/sim/sim_blast.py`
    — 08-11 run: NO runaway in sim at ANY friction (mu 1.0-2.0, the
    default already sits at the mu 2.0 saturation), every trap episode
    re-levels to <2 deg — the pinning gap is not a friction-magnitude
    story; tip1 outranks vref1 at nominal grip (0.88 vs 0.75 roll-trap
    pass), agreeing with the bench tally.**
-0.5 **GAIT CLEANUP — kill the paddle, walk TALLER (operator 08-11,
    TOP TRAINING PRIORITY; full design + rationale: `rl_docs/GAIT.md`;
    operator re-affirmed 08-11 afternoon: walking from a higher
    stance and walking without dragging feet are the same problem).**
    The walkers travel by dragging loaded feet (slip/m 1.1–1.5) at a
    ~50–77mm crouch; on hardware this scrapes and can catch.
    (P0, REWARD-ACCURACY DIAGNOSTIC — DONE 08-11 late: `--stack
    vref1` in `probe_walk_income.py`, GAIT.md bottom section.)
    Penalty-side suspect REFUTED: the plant-height tape-proven gait
    pays ≤1.5/ep total in gyro/roll/pitch and never terminates;
    totals are near parity (gait −11% at DR0, +8% at own-DR 0.35).
    The stack already favors tall by ~380/ep (stance kernel +
    k_height) but the crouch-paddle collects ~495/ep MORE walk+prog
    income because in sim it genuinely tracks the command (progress
    1.06 vs the gait's slip-limited 0.35) — a DISCOVERY/effectiveness
    problem, not a pricing hole. No repricing bank; proceed P2/P3.
    (P1, CLOSED 08-11) `cw-walk-gaitbc1` FAILED — BC-anchor gait
    cleanup froze into a static motionless tripod pose (video-
    confirmed, identical every episode, fwd ~0.00m vs parent's
    0.28-0.34m) instead of stepping: the anchor loss converged to
    ~0 by NOT MOVING (unlike rise/hold, walk's reference target is
    itself in motion, so freeze-toward-it looks satisfied). Per its
    own pre-registered gate, not a coefficient-variant situation —
    next is P2 or P3 lever 4. Detail: `rl_docs/GAIT.md`.
    (P2, CODE+bank LANDED 08-11 eve, operator session — CLAIMED,
    do not duplicate) charge-magnitude AUDIT DONE
    (`probe_drag_audit.py`): the per-tick charge FORM is refuted at
    any coefficient (0.5mm deadband left 53-97% of skating free;
    per-tick slip medians overlap gait's touchdown scuff), but
    per-STANCE accumulated travel separates skate from step 3.3x.
    Structural charge landed in walk_task (`reward.k_drag_stance`,
    `drag_stance_allow_mm`, `drag_stance_tick_floor_mm`; default
    off, bit-exact). Bank PASSING: step-gait > zero-lift skate AND
    > stall > park (test_drag_stance_stack_prices_skating_below_
    stepping). Operating point k=8000 / 6mm / 0.25mm (skater pays
    2.5x income, honest gait 23%). From-scratch arm = the operator
    session's next launch. Detail: `rl_docs/GAIT.md` bottom.
    (P2.5, TALL LADDER — operator session 08-11 eve, LIVE FLEET
    CAMPAIGN: run these follow-ups.) Height-as-COMMANDED-REF rungs
    work on the dep line where the hgt1 income gate did not:
    `cw-dep-tall30` (warm from tip1, walk_height_off_mm=-30 +
    k_drag_stance=8000/6mm/0.25mm, 2M) cut eval walk
    height_err_end 60mm→15mm at −24% speed (0.0295 vs 0.0388) and
    equal slip; isolation twin `cw-dep-tall30h` (no charge) is
    statistically identical (17.5mm/0.0287/1.80) → the charge is
    free, KEEP it; the speed cost belongs to the height rung.
    Rung 2 `cw-dep-tall15` (ref −15, warm from tall30) STALLED:
    body ≈ −44mm at either ref (err 29mm vs −15) — the free climb
    ends at ~−44mm (tip1 eval-ends ~−60mm). WHY THE FLEET MISSED
    IT: hgt1's FAIL verdict filed height as "cosmetic" and closed
    the thread; lowgait proved ref-rung tracking but ran DOWNWARD
    as a crouch envelope; nobody inverted it across lines.
    Pre-registered follow-ups (one variable each, warm from
    `ppo_goal_cw_dep_tall30` unless said otherwise; rung gate:
    height_err_end ≤8mm at ref, speed ≥0.028, survived 1, slip
    ≤1.8, no park):
    **T1 budget FAIL (08-11, `cw-dep-tall15-h1`, 6M):** not
       step-bound — `env/height_err_mm` plateaus by ~1M steps and
       sits flat the remaining 5M; harness eval end-state is WORSE
       than the 2M parent (51-58mm vs 29mm, near the tip1 ref-0
       baseline 59.9mm), with a bit more instability (one spinning
       episode, sto gait_valid 4/6). No cheat, still honest paddle.
       Do not schedule further step-count variants. Detail:
       GAIT.md. Next: T5 before T2/T3 (per this gate's own priority).
    **T5 DONE (08-11 eve, operator session — `probe_tall_wall.py`,
       landed):** the wall is HABIT/stability, NOT kinematics.
       Deterministic steady-state rollouts of the tall30 checkpoint
       vs the scripted plant-height gait in the same dep env:
       mid-gait the tall30 body rides **−75mm** with hip pitch −41°
       (≈70° of unused upward range) and knee 105° (≈46° room) —
       nothing pinned upward — but leg YAW is PINNED at its 35°
       limit (min margin < 0) with support radius 218mm vs the
       gait's 179mm: the policy buys lateral stability with
       splay+crouch. Scripted gait walks at +12mm in the same env
       (existence proof). **MEASUREMENT CAVEAT (binding):**
       `eval/walk/height_err_end_mm` is a STOP-WINDOW metric — the
       ladder's 60→15mm "gains" were mostly stop-stance recovery.
       Judge every tall arm by `probe_tall_wall.py` steady-state
       WALKING height (tall30 baseline −75mm; first target ≥ −50mm).
    **T3 result (08-11 eve):** 2M gate-at-reachable-ref
       (`cw-dep-tall-gate1`) holds 15mm/no factor collapse (0.58 vs
       hgt1's 0.24 crash) — gate and walking coexist. But the 6M
       hardening (`cw-dep-tall-gate1-h1`) is an INFORMATIVE FAIL:
       err 15→39mm — a σ30 income gate SLOWS but does not STOP the
       posture-for-speed trade under budget.
       **CONFIRMED 08-11 late (harness + probe_tall_wall.py on the
       actual checkpoint):** harness det height_err_end 36-47mm at
       DR0 (own-DR0.35 same band), speed 0.054-0.056 (above the
       speed bar, so this is a pure height loss, not a stall);
       steady-state walking height (the non-stop-window metric) is
       **-72.6mm, statistically the same as tall30's own -75mm
       wall** — 6M more steps under the gate bought ~2mm, not the
       ~45mm the σ30 gate was priced to hold. Leg-yaw limit margin
       still negative (-0.5..-0.3°, pinned at the 35° splay limit),
       same fingerprint as T5. Video clean six-leg gait, no cheat —
       an honest, informative miss. Gate-income alone is CLOSED as a
       lever at this dose; do not schedule another sigma variant.
    **T2/T4 VERDICTS (08-11 eve, probe_tall_wall mid-gait steady
       state): PRICING FAMILY CLOSED FOR POSTURE.** kh3 −74.5mm,
       kh10 −72.7mm (pays ~5.6/tick — MORE than its walk income —
       rather than stand up), slow1 −71.5mm at its trained 0.035
       cmd. Six arms total (ref ladder, income gate σ30, gate+6M
       budget, k_height 3x/10x, speed relief) all flat at
       −72..−75mm, leg yaw pinned at the 35° limit in every one.
       kh10's charge-eating proves the optimizer cannot FIND the
       taller basin — it is not underpaying for it. Do NOT launch
       more pricing variants for posture (incl. the yaw-splay charge
       candidate and σ45 — same family, pre-refuted by kh10).
    **T6 (RSI-for-walk) CODE LANDED + ARM RUNNING (08-11 eve):**
       `goal.walk_gait_start_frac` (walk_task + sim_env, default 0 =
       bit-exact, tests green): with prob f a walk episode spawns
       MID-STRIDE in the scripted tripod gait's tall pose, built at
       the episode's own command, command live from tick 0 (0.3 s
       ramp, no hold). Rationale: episodes always spawned tall
       STANDING — the missing states are tall mid-stride WALKING
       (same shape as the rise-RSI exploration closure).
       `cw-dep-tall-rsi1` = warm from tall-gate1, frac 0.5, 2M.
       If FLAT even with direct state injection: the wall is dynamic
       stability itself → physics easing or a taller scripted
       reference gait, not more reward work.
    **T6 VERDICT (08-11 late): FLAT — −77.4mm by probe.** The policy
       visits tall mid-stride states (50% of spawns) and actively
       dives back to the crouch (survived 1: it learned tall→crouch
       recovery, a robustness byproduct). CAMPAIGN CONCLUSION after
       7 arms + probe: neither pricing nor state injection moves
       mid-gait posture; crouch-splay is where PPO stabilizes this
       walk under current physics. Existence proof stands (scripted
       gait walks tall open-loop in the same env). Remaining levers
       in order: (1) **BC-INIT** — pure action pretraining on the
       scripted tall gait, THEN RL fine-tune under the gate income
       (different mechanism from the refuted gaitbc1 anchor-loss-
       during-RL, which could satisfy its loss by freezing; an init
       cannot); (2) physics easing ladder; (3) accept the pareto:
       `tall15_h1` (0.051 m/s, fastest dep walker ever, command-band
       for the first time) + tall STOP-stance for hardware, posture
       cosmetic. Byproduct: the 0.051 fast basin reappeared in rsi1
       — robust, reachable from multiple parents, and DEPLOYABLE
       (full dep contract) — bench-test it regardless.
    **BC-INIT WINS (08-12, `cw-dep-bcgait1`):** probe_tall_wall
       steady height -10..+6mm (every prior arm: -72..-75mm), leg-yaw
       margin +17..+18deg (every prior arm: pinned negative at the
       35deg limit) — the crouch+splay habit is GONE. Harness
       confirms real travel (prog_ratio 0.77, gait_valid 6/6, zero
       falls), video visibly taller and walking. Not yet polished:
       secondary slip bar missed (det 2.12 vs <=1.8, sto sacrifices a
       leg 1/6). Next: harden (more steps + DR/tipped retention) —
       GAIT.md bottom.
    Winner → Gate 0 export + tipped retention + bench A/B vs tip1.
    Checkpoints: `ppo_goal_cw_dep_tall30{,h}`, `ppo_goal_cw_dep_tall15`,
    `ppo_goal_cw_dep_tall15_h1` (fastest dep walker, 0.051 m/s),
    `ppo_goal_cw_dep_tall_gate1{,_h1}` on train-2; tall30 also on
    train-0 + the Mac (md5 a50a5d61).
    (P3, the goal state — operator: learn it WITHOUT the anchor)
    from-scratch curriculum line: terrain-as-teacher CLOSED for good
    08-11 (two-miss rule — 72mm collapsed to leg-sacrifice, 54mm
    avoided the sacrifice but paddled 4-6x worse than the closed
    band; bumpy ground never forces stepping, `rl_docs/GAIT.md`).
    Next: drag charge annealed up (needs the charge-magnitude audit
    first), physics easing, RSI-for-walk. The 10+ closed anti-slip arms
    were income shaping retrofitted onto formed paddlers — the
    closure does NOT cover P0's repricing (if the probe demands it),
    P2's banked structural charge, or P3's task curriculum
    (operator ruling 08-11).
0.  **UNIFIED JOYSTICK POLICY (top deliverable).** Stand/sit/walk in
    one checkpoint (turning: see 0.2). Live experiment:
    `cw-uni-flag-a1-h2` (10M hardening) finished 08-11, verdict
    pending — decides one-brain vs MoE. Rise: problem 2.
    Line gate: joystick-gate retention AND rise/lower ≥5/6 AND quiet
    hold AND clean video on the post-273ebde floor.
0.2 **TURNING — RE-OPENED (operator 08-11 afternoon); steps 1–2 DONE
    08-11, step 3 QUEUED. Full results: `rl_docs/TURN.md` (bottom
    section).**
    (1) REWARD AUDIT — DONE, defect FIXED + BANKED: two cfg-gated
    fixes in walk_task.py (`reward.walk_yaw_hold_prog_gate` —
    heading-hold yaw income gated on achieved linear progress;
    `reward.yaw_still_avg_s` — drift charge on the wz EMA, not the
    gait's zero-mean oscillation). Pre-fix the yaw stack paid a
    frozen body +375/ep vs the honest gait's +224 net; post-fix
    income is monotone in honesty (gait 935 > … > driftride 715 > …
    > freeze 242) with a drift-rider calibrated to ACHIEVE the
    measured 0.09 rad/s. New stillness-subsidy bank (4 tests, incl.
    a legacy-stack reproduction and the full-summed-stack
    drift-rider check the old bank missed) green; TURN_OVERRIDES
    trains both fixes ON. The yawcmd1/yawgate2/turnfix1 ckpts no
    longer exist on any pod — ckpt-level audit closed UNTESTABLE.
    (2) REFLECTION WRAPPER — DONE, PASS: `mirror.MirrorPolicy` +
    `probe_mirror_turn.py` on cw-dep-vref1-r1 — mirrored policy
    drifts −0.040..−0.046 vs naked +0.037..+0.062 rad/s with
    IDENTICAL travel at DR 0 and DR 0.35, zero falls; bang-bang
    alternation holds heading to 2–4 deg over 12 s vs 34–50 deg
    naked runaway. Arc-left/arc-right/straight by chirality
    selection, zero training — but at the drift rate (~2 deg/s), so
    commanded-rate tracking stays open. Deploy port + rot60
    composition are follow-up [CODE]; sign audit CLOSED 08-11 night
    (operator: turns as drawn, both signs — no bridge flip).
    (3) MIRROR-SYMMETRY TRAINING — RUN AND FAILED 08-11 late
    (`cw-walk-mirturn1`, discovery 2M, warm from vref1-r1, full fixed
    pricing, mirror coef 1.0): sym loss converged 28→0.5 but turn
    tracking never arrived (|wz_err| med 0.254, L/R asymmetry intact)
    AND the forced symmetry rewrote the gait (prog 0.41 vs ~1.0, slip
    5x parent). Mirror TRAINING on a warm champion is CLOSED per the
    pre-registered gate; MirrorPolicy chirality selection is the
    shipped turning story (deploy port + rot60 composition [CODE]).
    (4) BC-ANCHOR ON TURN TICKS: in reserve, unpromising after
    transbc1's walk-tick freeze.
0.3 **FOUR-LEG WALKING — NEW line (operator 08-11 afternoon).** The
    target image: the robot SHIFTS ITS WEIGHT BACK onto the four
    rear legs and walks on them, front pair raised off the ground as
    "hands". Never attempted; feasibility is GO (c57 sweep: 39mm
    static margin with CoM shift + rear-leg splay), and the quad
    HOLD mechanism is already solid (quad-hold2, dep-quad1-c2).
    SPECIFICATION FIRST — the current reward punishes this behavior
    by design, in two independent ways ("is the reward incentivising
    the correct behavior" — here, provably not yet):
    (a) the walk stack's anti-cheat machinery (park-duty charge,
    step-event credits, flag-leg/sacrificed-leg detectors,
    gait_valid) literally DEFINES a four-leg walk as the
    leg-sacrifice cheat we spent weeks stamping out — every
    accounting term must become lift-command-conditioned (commanded-
    lifted fronts excluded from park/step/flag checks and paid via
    quad_clear/quad_plant-style income instead);
    (b) the rear-shifted posture fights k_pitch/k_roll and the
    tilt-termination envelope, which are referenced to LEVEL — quad-
    walk episodes need a commanded posture reference (the inverse of
    the tipped-start level-reference trick) so tipping back on
    purpose isn't charged or terminated.
    Then the bank BEFORE any launch: honest four-leg stepping must
    out-earn (i) ignoring the lift command and walking on six,
    (ii) standing still on four, (iii) uncommanded leg sacrifice —
    and the rear-shift posture must be net-non-negative under the
    fixed pricing. Train as a SPECIALIST (warm from quad-hold2 or
    the walk champion): four dose points prove quad/walk mixing
    erodes walking, so no mixed-diet arms. If discovery stalls,
    write a scripted rear-four diagonal-pair gait (TripodGait
    variant on legs 1,2,3,4) as a BC-anchor reference.
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
    3. **Hold/track stillness pricing — SOLVED 08-11 (BC-anchor
       extended to hold/track ticks; two pricing-only levers failed
       0/12 first).** `cw-stand-holdbc1` PASSES (hold 12/12
       valid_plant det+sto, first genuine quiet hold); 10M hardening
       `cw-stand-holdbc1-hard1` PASSES with no regression —
       `ppo_goal_cw_stand_holdbc1_hard1` is the hardened HOLD+RISE
       checkpoint (SKILLS.md), lineage CLOSED. **BOTH handoffs PASS
       (eval_handoff.py / eval_handoff_reverse.py): the full sim
       joystick motion cycle (rise→drive→stop→sit) composes with
       zero falls**; the scripted go_zero-sit glide (6/6 both
       physics) covers the deliverable's sit. Optional unqueued
       polish: BC anchor on lower ticks. **Deploy-side port LANDED
       08-11 late**: runner stance slot runs the specialist, goal
       profile rides in the weights meta, test_stand_runner.py locks
       the contract — remaining work is BENCH-ONLY. Numbers/evidence:
       rl_docs/RISE.md.
    4. mode/command one-hot — LANDED 08-11 (see Architecture);
       machine-readable metric semantics registry (RESEARCH_RULES);
       contact-from-proprioception aux head; zero-drift DR mechanism
       rework (open problem 5). **LOWER bank
       LANDED 08-11 (last owed bank; TURN/WALK landed earlier):**
       under the deployed specialist stack, honest command-tracking
       descent out-earns the outrig/aloft cheats on every seed
       (540 vs 461/383) and posture-strict rejects them (pads ~300 mm
       vs ~0) — lower-mode arms are unblocked. KNOWN THIN MARGIN
       (strict-xfail in the bank): pf=5/6 pricing lets one-leg-aloft
       keep 85% of honest income — the incentive behind the deployed
       specialist's cosmetic dangling foot; strengthen pricing or
       BC-anchor lower ticks before any lower-MECHANISM arm.

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
