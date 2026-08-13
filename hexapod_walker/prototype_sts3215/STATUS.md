# STATUS — how is it going?

**START HERE, then go to your track.** The campaign runs as six
parallel research tracks, and the current state of each line of work
lives in its own short per-track status file — read the one you care
about first:

- `rl_docs/tracks/hw/STATUS.md` — joystick robot on real hardware
  (the mainline)
- `rl_docs/tracks/arch/STATUS.md` — GRU/temporal architectures
- `rl_docs/tracks/nobc/STATUS.md` — learning without BC anchors
- `rl_docs/tracks/quad/STATUS.md` — four legs + two "hands"
- `rl_docs/tracks/turn/STATUS.md` — commanded turning
- `rl_docs/tracks/multitask/STATUS.md` — command-conditioned
  generalist vs sequential specialists

This file is the whole-campaign digest: the plain-English answer to
"how is it going, what can the robot do now, which checkpoints are
the good ones, and what have we learned?" — for the operator or
anyone catching up. Facts here must agree with `CURRENT_TRUTHS.md`
(which wins on conflict); the full checkpoint inventory with gate
numbers lives in `rl_docs/SKILLS.md`.

**Last updated: 2026-08-13 (~13:xx UTC — WAITING-ON block pruned to
LIVE waits only per the 08-11 "removed in the cycle that clears it"
rule; every cleared entry's resolution narrative is preserved in its
track STATUS doc / rl_docs/runs/ / RISE.md / GAIT.md / SIM.md and in
git history. Headline ~12:xx) — the standing-lean saga
(tiltcomp1→2→3) is CONCLUDED in sim: both fixable-by-training levers
(teacher design, then 4× training exposure) are now exhausted, and
the ~8° hardware lean is a live OPERATOR DESIGN CALL (see
WAITING-ON).** A probe that rolled out the tilt-comp anchor TEACHER
itself found the first teacher mathematically incapable (a perfect
student tops out ~4°, a P-controller fixed point) and fixed it
(settle-lean design, probe-verified to level a perfect student to
1.76°) — `cw-stand-tiltcomp2` trained that fix and still failed,
but cleanly: the policy only ADOPTED ~10% of its now-capable
teacher's correction. The obvious next lever, quadrupling how often
the robot practices tipped recovery (`cw-stand-tiltcomp3`, hold-mix
0.1→0.4), barely moved adoption (10%→20%, needs ≥50%) and — new
finding — leaked the same one-foot-park habit into the ORDINARY
(untipped) stance, which had never shown it before. Teacher
capability, hold income, and now training exposure are all measured
innocent; the operator's two remaining options are pricing residual
lean directly in reward, or treating the lean as a hardware/
mechanical trim problem outside RL. The deployed stance checkpoint
is unaffected either way. Earlier (~13:xx local) — the interactive SESSION gate
(the deployment-contract eval that separated the stance candidates
from the deployed policy) is now AUTOMATIC: the watcher's pre-staged
pod evals run `eval_session` on every finished stance/walk candidate
(WISHLIST 8e landed — seat rule + tests in `pod_eval.py`, cv2→PIL
strip fix so it runs on the train pods; verified end-to-end on
train-0). No training implication; every future candidate's triage
now sees the interactive-protocol result without asking. Earlier
(~12:xx) — quad diag session: the
open question "can any scripted gait walk on four legs?" is now
ANSWERED, negatively and permanently — an instrumented probe
session measured that a statically-stable open-loop quad crawl with
both fronts lifted is geometrically infeasible on this robot (the
mid-swing support triangle needs the CoM 5-7 cm further back than
the ±35° hip-yaw workspace can ever place it). Four-leg walking is
possible only with closed-loop balance, so the quadwalk bank's
reference is now an operator-only ruling; quadwalk training stays
correctly launch-blocked (see the quad WAITING-ON entry). Earlier
(~10:xx) — quad spec cycle: the four-leg-WALK mode/reward/eval code
is built and checked in (default-off, banks green). Earlier (~08:xx) — the standing-lean fix attempt
failed: `cw-stand-tiltcomp1` (tilt-aware anchor teacher) reproduces
the stay-tilted habit (~5.75° lean, 24/24 episodes) instead of
leveling; tipped-exposure training is CLOSED with two teacher designs
now converged on the same pathology, and the hardware ~8° lean
escalates to an operator design discussion (see WAITING-ON).**
Earlier (~06:xx) — headline CORRECTED: the
warp-vs-C contact parity audit ran and the GPU training physics is
FINE. Matched command-stream replays (new `probe_contact_parity.py`)
show warp@1/4 within ~3–6% of C@50 on loaded-foot slip in both the
normal and the no-slip speed regimes, flat across solver iterations,
zero stance creep under pure load — the earlier "under-charges slip"
headline compared a stochastic training metric against a
deterministic probe and is retracted; no campaign-wide physics fix is
coming, slip levers stay reward/BC-side. The arch no-slip line
CONCLUDES at its gate-passing r4 walker (RL preserves the taught
no-slip gait; adding more needs a new mechanism — see arch/STATUS.md).
Earlier 08-13 (~05:00): nobc's
from-scratch gait line is out of levers after `cw-gait-ease1`
(physics easing, the last planned lever) froze exactly like its five
predecessors; recommendation to the operator is to CLOSE that line
(see WAITING-ON). Fleet 0/12 training, all idle slots named waits.
Previous headline (08-12 evening) — stance line: the 10M
consolidation `cw-stand-footlow2-hard1` PASSES all four
pre-registered gate clauses at once — the first stance checkpoint
with clean rise (incl. cold flat, confirmed 12/12 via a targeted
probe), a genuinely park-free six-foot hold, clean 12/12 lower, AND
a pass on the tougher interactive `eval_session` hard gates that the
currently-deployed `holdbc1_hard1` FAILS (that checkpoint stalls its
belly rise at 55mm under the interactive ramp; this one reaches the
full 148mm). Visual-quality stats (drag, roll-tail) are flat-to-
better than its parent on every mode, video-confirmed. It is a
genuine sim-side stance DEPLOYMENT CANDIDATE (`ppo_goal_cw_stand_
footlow2_hard1`, not yet bench-tested) — whether it replaces
`holdbc1_hard1` as deployed is the next call. Earlier same day: the
dig-in that got here overturned both of footlow2-r1's flagged
residuals (flat rise was solved all along, mislabeled by the eval;
the "reopened park" was a sub-mm cosmetic hover) — see hw/STATUS.md
for the full chain. Earlier midday: the session ramp-jitter axis
(`cw-stand-rampjit1`) FAILED and is CLOSED (next lever: start-state
exposure). See WAITING-ON below.**
Update rule: refresh whenever a hardware session happens, a champion
changes, or a big lesson closes — and stamp the date; per-track story
changes go to the track's own STATUS.md. Keep it honest: the "not
working" list is the most valuable section.

## READ FIRST — operator ground truth (08-11 night), and what is blocked

**The operator watched the deployed stand and walk in the MuJoCo
viewer and on the robot, and both are visibly busted.** That verdict
outranks every sim gate number below (CURRENT_TRUTHS: real-robot
facts win). Concretely, camera-verified by the nine unattended bench
sessions tonight (`rl_docs/BENCH_REPORT_2026-08-11.md`):

- **The learned stand-up fails on hardware 10 times out of 10** — it
  trips the roll limit at the same tick of the belly curl every
  single time (10.1–10.6° vs the 10° limit, mid-curl rocking the sim
  never shows). The scripted stand glide is the only working stand.
- **Learned walks fall roughly half the time within seconds of
  takeoff** (vref1 6/10 fell, tip1 4/7; every walk swings 13–27° of
  roll in the first ~2 s; survival is luck, not skill). Neither
  policy is better — surviving the takeoff transient is the problem.
- **The robot drags its feet** — during walking (the low crouch
  shuffle, slip ~1.0–1.5 m per meter of progress even in sim), and
  worse, during stand/sit transitions, where until tonight NOTHING
  in the reward even priced a loaded foot scraping the floor.
- Past sim gates were measuring "didn't fall / reached height", not
  "looks right" — which is how every status update stayed optimistic
  while the robot got worse. Tonight the evals gained the operator's
  eyes: hardware-comparable roll peak/tail/settled stats and per-
  episode foot-drag meters in every eval line (`rl_docs/EVALS.md`),
  and a new `reward.k_drag_trans` charge prices the stand/sit scrape
  (bank-verified, `rl_docs/REWARD.md`).
- **08-12 sim-side good news: the low-crouch/leg-splay walking habit
  is broken for the first time (`cw-dep-bcgait1`)** — after ten-plus
  reward/pricing/state-injection attempts went nowhere, pre-teaching
  the network the scripted tall gait's ACTIONS (then RL fine-tuning)
  got it walking within a centimeter of full standing height with
  legs no longer jammed sideways, genuinely covering ground. Not
  hardware-ready yet (feet still slide more than the bar allows, one
  in six stochastic runs still drops a leg) — next is hardening.
  Detail: `rl_docs/tracks/hw/STATUS.md`, `rl_docs/GAIT.md`.

**WAITING-ON / fleet state (rule: anything the orchestrator is
waiting on goes HERE, at the top, the moment it starts waiting —
named concretely, REMOVED in the cycle that clears it; resolution
narratives live in the track STATUS docs, rl_docs/runs/, RISE.md /
GAIT.md / SIM.md, and RL_LOG — not here):**

- **FLEET: 0/12 pods training, backlog empty (since 08-13 ~03:1x;
  re-verified 08-13 ~11:4x UTC).** Every idle slot maps to a named wait
  below. No unattacked sim stand/walk blocker remains: the
  one-parked-foot hold and det flat-rise stall are SOLVED
  (footlow2-hard1), the crouch-splay tall-walk wall is BROKEN
  (bcgait1-hard1), contact/pinning + warp physics are audited clean,
  and the two open transients (takeoff roll, standing lean) are the
  operator forks below.
- **hw — standing-lean design fork (since 08-13 ~12:xx).** The ~8°
  hardware standing lean: both training-side levers are measured
  exhausted (tiltcomp1/2/3 — teacher design proven capable, hold
  income already pays leveling, 4× tipped exposure moved adoption
  only 10%→20% vs the ≥50% bar AND leaked the one-foot park into the
  nominal untipped hold; the untrained parent's innate 1.45°
  recovery beats every tipped-trained child). Blocked on an OPERATOR
  DESIGN CALL: price residual lean directly in hold income (a new
  reward term — note three prior pricing terms on anchored stance
  were all evaded by parking) vs. treat the lean as hardware/
  mechanical trim outside RL. No tipped-exposure or teacher arm may
  queue without it. `holdbc1_hard1` stays deployed, unaffected.
  Detail: hw/STATUS.md Now, RISE.md.
- **hw — stance promotion is a BENCH call (since 08-12 eve).**
  `cw-stand-footlow2-hard1` passes the full stance gate incl. the
  interactive `eval_session` hard gates the deployed `holdbc1_hard1`
  fails (148mm vs 55mm belly rise under the interactive ramp);
  `footlow2-stable1` is a second passing candidate (real hold-drag
  tradeoff vs hard1, +75%). Blocked on: operator bench session +
  promotion decision. Detail: hw/STATUS.md, SKILLS.md.
- **hw — tall-walk Gate 0 needs BENCH TAPE (since 08-12).**
  `cw-dep-bcgait1-hard1` (tall-walking champion: BC-INIT broke the
  crouch-splay wall, 10M hardening PASS, fric + groundtilt5 panel
  axes PASS, push-probe falls no worse than tip1 with zero push
  exposure). Blocked on: hardware bench evidence — per its own
  ruling, NOT another sim DR axis. Detail: hw/STATUS.md, GAIT.md.
- **hw — walk-takeoff roll transient: operator design discussion
  (since 08-12).** All three perturb-during-training families are
  closed (walk-kick, rise-rock incl. ramp-gated shape fix,
  walk-push at 2M and 10M), the contact/pinning hypothesis is
  falsified (tape replay: curls never touch the chassis), and warp
  physics is exonerated (parity audit 08-13). No launchable sim
  lever is named; nothing trains against this blocker. Detail:
  hw/STATUS.md Next, SIM.md gap 4.
- **multitask — direction call (since 08-13 ~00:3x).** The wave-1
  acquisition shortfall's whole cheap-lever menu FAILED (capacity/
  arch256, staged widening at 2M and 20M, obs history at 2M and
  20M). Options on the table: transplant arch's dual-core recurrent
  architecture (cross-track launch = operator-only), narrow the
  command-width curriculum, or accept `b2` as this recipe's ceiling.
  `eval_cmd_suite.py` is pre-built for whichever direction. Detail:
  multitask/STATUS.md.
- **arch — waiting on the operator's in-progress DAgger rise
  redistillation (since 08-12).** The dual-GRU line's rise gap is
  BC-demo data poverty (hfloor1 refuted the supervision-aim lever);
  the no-slip line CONCLUDES at its r4 gate-pass artifact. No
  agent-side arm without new demos. Detail: arch/STATUS.md.
- **nobc — close the from-scratch gait line? Operator accept/reject
  (since 08-13 ~03:1x).** All five planned levers closed honestly
  (`cw-gait-ease1` froze identically even at half gravity).
  Recommendation: CLOSE (nobc keeps its stand-from-scratch charter).
  The build-first ASSUMPTION for the ease code is on record in
  nobc/STATUS.md (mechanism default-off, nothing else trains on it).
- **quad — MDP_PREFLIGHT ruling needed (since 08-13 ~08:xx).** A
  statically-stable open-loop quad crawl is measured GEOMETRICALLY
  INFEASIBLE (CoM needs 5–7cm more aft than the ±35° hip-yaw
  workspace can place it), so no scripted bank reference can exist;
  the only route is the operator accepting a future RL/feedback
  rear-four-stepping policy as the quadwalk bank reference. The
  quadwalk mode/reward/eval code is built, default-off, and
  correctly launch-blocked meanwhile. Detail: quad/STATUS.md.
- **turn — MirrorPolicy deploy port (since 08-11).** Robot-runner
  work, operator-only by guardrail; the quad-turn rung closed 08-13
  behind the track's needs-new-idea wall. Detail: turn/STATUS.md.
- **dynrep — blocked on the operator pushing `rl_move/dynamics/`
  (since 08-12 ~21:40, surfaced 08-13).** The track's code +
  datasets/checkpoints are laptop-local (commit 7b83dce registered
  the track only). Cycles will not rebuild it from the design doc —
  that would fork the operator's in-progress local work.
- **Bench session items (operator time, not GPU — nothing is
  deploy-blocked):** first hardware run of the learned stand-up
  (deploy re-push DONE + HTTP-verified 08-11 ~21:15, goal profile in
  the meta), rot60 off-wedge headings, the vref1-vs-tip1 A/B on one
  floor, tape reading on an RL walk. Turn-sign audit CLOSED (signs
  match both ways). Session runner: `rl_move/scripts/bench_blast.py
  --go`.


## The one-paragraph answer

The real robot walks — under the scripted gait (tape-measured), AND
a learned policy has now driven it: on 08-10 night `dep-tip1` walked
level on real ground in 3 of 4 runs. The deployment-contract
champion `vref1-r1` itself went 0-for-2 with an intermittent runaway
roll (a pinned loaded leg feeds a lean that the policy never
recovers — a sim-to-real contact gap, since sim recovery can exploit
feet that skate). That runaway is THE open hardware question: the
discriminating vref1-vs-tip1 A/B on the same floor ran tonight and
has NO winner — both fall about half the time at takeoff (see READ
FIRST). In simulation the joystick motion cycle completes end to end
without falling — but "without falling" is the whole claim: the walk
is a low crouched shuffle that drags feet (slip ~1.0–1.5 m per meter
of progress), the stand-up that looks smooth in sim rocks over and
trips 10/10 on the real robot, and the stand/sit transitions scrape
feet across the floor (unpriced by any reward term until tonight).
The operator has seen all of this in the viewer; the eval stack now
measures it (roll tail/settled + drag meters, EVALS.md).
The two breakthroughs that got us here (both 08-11): first,
**BC-anchoring** — instead of tuning reward prices yet again, we pull
the policy's actions directly toward a recorded good motion during
training; that one trick solved standing up AND holding still after
roughly seven straight reward-tuning failures each had cheated.
Second, **the hexagon trick** — the robot is a perfect hexagon, so
"walk backward" is literally "walk forward with the legs relabeled";
a small math wrapper (`rot60.py`) gives the existing hardware
checkpoint the full circle of directions with ZERO training, closing
a problem four training runs had failed at. Turning was briefly
de-scoped (no camera = no "front" to point), RE-OPENED the same
afternoon — and promptly cracked half-open: the turn reward's real
bugs are fixed and banked, and a second symmetry trick (the mirror
image of the walk policy turns right exactly as well as the original
drifts left) now gives slow bidirectional steering with zero
training; a queued run goes after fast commanded turns. Two more
wanted skills opened alongside: four-leg walking (weight shifted
back, front legs raised as "hands") and walking taller without
dragging feet. All are diagnosis-first: audit
whether the reward actually pays the desired behavior before
launching arms (see "what happens next"). The evening's verdicts:
the one-brain flagship question is SETTLED by measurement (a
stand-up-only control run plateaued at exactly the multitask
flagship's 1-in-6 — the skills were never fighting for space, so the
mixture-of-experts rebuild is off the table; stand-up-from-scratch is
just hard for any network with this recipe), and the walk-gait
cleanup's two cheap levers both closed (BC-anchoring the gait froze
the robot into a static tripod; bumpy ground made the paddle WORSE,
never forced stepping). The GRU line, frozen this morning, was
deliberately reopened in the new arch research track with the two
levers its last failure pre-registered (4x longer memory window +
double capacity) — running now.

## What the robot can do — REAL hardware

- Walk forward, crab sideways, and turn in both directions from a
  clean zero, under the scripted tripod gait. Tape-measured: ~50% of
  commanded distance (real foot slip, and that's fine — visible slip
  is part of how this robot locomotes).
- Servo current tracks how hard servos FIGHT their command, not the
  pose: walking 0.33–0.45 A, scripted stand 0.54–0.59 A, walk-stance
  hold ~0.11 A. ("Standing costs more than walking" was really
  "fighting your own command costs more than walking.")
- **Walk under a LEARNED policy — sometimes.** `dep-tip1` (tipped-
  start retrain of the champion): 3 clean level walks / 1 runaway
  roll on 08-10 night; obs pipeline verified bit-exact against sim.
  The champion `vref1-r1` went 0/2 with runaway roll. The visible
  "sag" is the trained walking posture (commanded, not servo slip)
  and the scraping is the known low-clearance shuffle — the gait
  cleanup line exists exactly because of this.
- Not yet tried on hardware: the rot60 any-direction wrapper and the
  learned stand-up specialist (both ported 08-11, need a deploy
  re-push; do not press STAND on the stale on-robot copy).

## The best checkpoints, per skill

| Skill | Best run / checkpoint | Where it stands |
|---|---|---|
| **Walking with the joystick (hardware candidate)** | `cw-dep-tip1` (active walk slot) over `cw-dep-vref1-r1` (md5 f9a466cf) | tip1 = vref1-r1 + tipped-start DR: 3/4 clean level walks on real ground 08-10 vs the parent's 0/2 runaway roll. Both contract-exact, both on the robot picker. Open: the same-floor A/B (roll-ramp rate, runaways per N runs) and an RL-walk tape reading. |
| **…in any direction (full circle)** | same checkpoint + the `rot60` wrapper | Zero-training math fix; default-ON in the robot runner; backward went from frozen (3 cm of a commanded 30) to tracking as well as forward. Bench validation pending. |
| **Best pure-sim driving envelope** | `cw-walk-joyheadfric` (and its payload variant) | ±90° steering + latency + floor-grip + payload, 3-seed confirmed, joystick gate zero falls. Superseded for hardware by vref1-r1 (deployment contract), but it's the widest proven driving recipe. |
| **Standing up AND holding still** | `cw-stand-holdbc1-hard1` → `ppo_goal_cw_stand_holdbc1_hard1` | The deployed stance policy (robot's stand button), with its trained goal ramp shipped inside the weights. Hold 11/12 strict-valid, motionless on video; rise from flat belly reliable. |
| **Crouch-start stand fix** | `cw-stand-crouchrise1`/`-2` — **banked, NOT deployed, do not warm-start** | The fix reproduces cleanly (crouchrise2: 6/6 det rises incl. all crouch starts, zero falls) but BOTH variants park the same two feet in the air during hold — even with the deployed policy's exact training mix restored. Start-mix lever closed (two-miss rule); next lever is code: a state-aligned BC anchor (see "not working"). |
| **Turning on command** | `cw-dep-vref1-r1` + the new mirror wrapper (`mirror.MirrorPolicy`) — sim-proven 08-11, deploy port pending | Second hexagon trick: the mirrored policy turns RIGHT exactly as the naked one drifts left, same speed, zero falls; flipping between them steers both ways and holds a straight heading (2–4° over 12 s vs 38° drift). Slow (~2°/s) — and now the shipped story: the mirror-symmetry TRAINING run (`cw-walk-mirturn1`, 08-11 late) failed its gate (no turn tracking, gait degraded), closing that lever. |
| **Four-leg stand (party trick)** | `cw-quad-hold2` (30% mix on the walk champion); `cw-dep-quad1-c2` on the deploy contract | Mechanism is solid (lifts fronts, level, never tips) but ANY mixing dose erodes walking — stays a deploy-time specialist. |
| **Four-leg walking** | never attempted — NEW line opened 08-11 afternoon | Target: weight shifted back onto the four rear legs, front pair raised as "hands". Feasibility GO (39 mm margin). Spec first: today's reward provably punishes this exact behavior (RL_PLAN queue 0.3). |
| **Legacy sim walk champion** | `ppo_goal_cw_walk_longdist_r2` (md5 bcddc65c) | Seed-confirmed forward walker the whole driving line descends from; kept for sim work. |

## Best "leaning on a reference" vs best "from scratch"

**Best BC-anchor model: `ppo_goal_cw_stand_holdbc1_hard1`** (the
deployed stand+hold specialist). BC-anchor means: during training,
alongside the normal reward, the policy's actions get pulled toward
what a known-good recorded motion did at that moment. The cheat can't
farm it because it isn't reward income. It solved stand-up
(`cw-stand-bc1` → `bc1-hard1`: 12/12 honest stands where six
reward-only attempts all cheated) and holding still (`holdbc1`:
first genuinely motionless hold in the campaign). Important limit
discovered the same day: BC-anchor fixes "the trainer can't find the
right LOCAL motion" but NOT "the trainer can't find a different
GLOBAL pattern" — anchoring walk ticks to a scripted gait did nothing
for walking in new directions (`cw-omni-transbc1` failed; the
imitation error converged and the robot still didn't travel), and the
BC-anchor attempt at cleaning up the paddle gait failed the same way
(`cw-walk-gaitbc1`, verdict 08-11 evening: the anchor converged and
the policy froze into a static tripod pose instead of stepping).
That's now a three-time lesson: BC-anchor fixes local motions, never
gait patterns.

**Best from-scratch model: the entire walking/driving lineage.**
Every walker — `longdist_r2`, the joystick family, `vref1-r1` —
descends from `step0` (08-08), a fresh network trained with reward
only: no demonstrations, no reference motions. What made that work
was reward design (step-event income + drag + park-duty pricing),
not any warm start. The purest recent from-scratch results:
`cw-arch-hist16-dep1(-c1)` (16-frame history net learns to walk from
scratch under the full deployment contract, two seeds) and
`cw-uni-flag-a1-r1` (the flagship: from scratch, one network learned
a perfect quiet hold 6/6 AND a clean sit 6/6 in only 2M steps, with
honest-but-unfinished stand-ups — no cheating, no skill fighting).

## Bigger models — history MLP, GRU, and the flagship

- **Baseline** is an 8-frame history MLP (the policy sees the last 8
  observation frames stacked).
- **hist16 (16-frame history MLP): works, and is the preferred base.**
  It learns to walk from scratch (seed-confirmed, joystick gate
  clean) including under the full deployment contract
  (`cw-arch-hist16-dep1`). But piling on more training stopped
  helping (`r7-c4`: +40M steps bought nothing) — the remaining gait
  quality gap is sim contact pricing, not network memory.
- **hist24: trains, but slip/economy came out worse than hist16.**
  The ladder is frozen at 16 by operator ruling.
- **GRU (recurrent memory): failed three times walking — but learns
  every STANCE skill to champion grade — and is now REOPENED with the
  pre-registered levers.** `r1`/`r2` collapsed into the classic
  fake-walk (three legs parked, training reward climbing the whole
  time). `r3` re-ran with the FULL anti-cheat reward stack that fixed
  exactly this exploit on the MLP line — and it still cheated at
  walking while mastering hold/rise/lower. So for the GRU walking is
  genuinely not a reward problem at that size/window.
  `cw-arch-gru-r4c` (running, arch track) tests the two levers r3's
  failure named: 4x longer memory window (10.24 s) + double hidden
  size, at r3-identical update counts. If the cheat survives both,
  from-scratch GRU walking closes at this budget.
- **The flagship (one brain for everything): the big fork is SETTLED
  — no mixture of experts.** hist16 + a bigger 256×256 network + an
  explicit "which skill am I being asked for" input, from scratch on
  hold/rise/lower. Stage A passed hold and sit at specialist quality
  (first time one network did both honestly from scratch); stand-up
  plateaued at 1-in-6 and the 10M hardening run (`cw-uni-flag-a1-h2`)
  bought nothing — hold stayed clean, sit even improved, rise
  identical to the 2M parent, honest sprawl/tip-over failures on
  video, no cheating. The decisive measurement: the identical brain
  trained on stand-up ONLY (`cw-uni-flag-a1-risectl1`, 2.5x the rise
  practice, zero competing skills) scored exactly the same 1-in-6.
  Removing every other skill changed nothing, so the skills were
  never fighting for network space — the MoE rebuild is refuted by
  measurement, not just deferred. Stand-up-from-scratch is simply
  hard for any network with this recipe (the dedicated specialist has
  the same crouch-start struggle). Not a hardware blocker (the
  specialist-handoff stand-up covers the bench plan); if the line
  reopens, the lever is seeding from the specialist, not another
  reward or architecture change.
- **The meta-lesson: architecture was never the bottleneck.** Every
  time a skill failed, the fix turned out to be the task spec (reward
  semantics, supervision, start distribution) or free structure
  (geometry) — never a bigger or fancier network. Bigger models are
  worth having (the flagship needs the capacity), but reaching for
  one to fix a failing skill has been wrong every single time.

## What is NOT working (the honest list)

- **A learned policy on the real robot.** Attempt #2 is the entire
  critical path: walk + full-circle wrapper + the learned stand-up
  are all staged. Start with a fresh `set_zero`, and re-push/select
  the profile-carrying stand export first — the copy activated on the
  robot on 08-11 morning lacks the goal-ramp profile and would feed
  the policy an out-of-distribution ramp (see HARDWARE.md).
- **Turning on command (RE-OPENED 08-11; big progress the same
  day).** Policies carry a baked-in left-yaw drift and ignore the
  yaw channel. Three things happened 08-11 afternoon (detail:
  rl_docs/TURN.md, bottom): (1) the suspected turn-reward bugs were
  REAL and are now FIXED and bank-tested — the turn stack literally
  paid a frozen robot more yaw income than an honest walker
  (+375/ep vs +224), and its "anti-drift" charge taxed the honest
  gait's natural wobble while charging the cheats nothing; both
  terms are repriced and a new bank test reproduces the old bug and
  proves the fix. (2) the ZERO-TRAINING mirror trick WORKS in sim:
  the hexagon is left-right symmetric, so reflecting the deployed
  walk policy produces an equally good gait that drifts RIGHT
  instead of left — switching between the two steers both ways and
  drives straight (heading held to 2–4° where the naked policy
  drifts off by ~38°). Caveat: it turns at the drift rate (~2°/s),
  so it's steering, not a pirouette. (3) with the reward verified,
  the mirror-symmetry TRAINING run finally ran (`cw-walk-mirturn1`,
  08-11 late) and FAILED: the symmetry penalty converged but turn
  commands still aren't followed, baseline drift tripled, and the
  forced symmetry rewrote the champion's gait into near-in-place
  churning. That closes mirror TRAINING; the zero-training mirror
  wrapper IS the shipped turning story (slow steering). Hardware
  sign audit (does sim "+yaw" match robot "+yaw"?) still gates any
  bench turn session.
- **Gait quality: the champion walks by paddling, in a crouch**
  (loaded-foot slide, slip ~1.1–1.5 m per meter, body at ~50–77 mm
  below plant height). On hardware this scrapes. Walking taller and
  not dragging feet are the same problem (operator). The evening
  closed BOTH cheap levers (two-miss rule, detail `rl_docs/GAIT.md`):
  BC-anchoring the gait to the scripted tripod froze the robot into a
  static pose (`cw-walk-gaitbc1`), and terrain-as-teacher is refuted
  decisively — on real 36–108 mm bumps the paddle's slip gets
  monotonically WORSE, never better; from-scratch training on true
  72 mm ground learned leg-sacrifice dragging (`cw-gait-terrain2`,
  `-r1`), and a 4x drag charge from scratch formed the paddle anyway
  (`cw-gait-dragstep1` — with the caveat that the effective charge
  never exceeded ~0.09/tick vs ~1/tick income, so a "really big"
  penalty is still untested). What remains is spec/code work before
  any launch: the reward-accuracy probe (replay the tape-proven real
  gait AT HEIGHT through the full stack — the real gait rocks
  ±10–20°, which our tilt pricing charges, so the reward may be
  paying the robot to stay low and smooth), the drag-charge magnitude
  audit, and the P2 structural stance-slip charge with its bank.
- **Crouch-start stand-ups.** The fix is proven and REPRODUCES
  (`crouchrise1`: 16/16 crouch stands vs 0/8 before; `crouchrise2`:
  6/6 det rises incl. all crouch starts, zero falls) — but both
  variants break the hold the same way: two feet quietly parked in
  the air, the SAME two legs both times, a resurfaced flag-leg cheat
  that the strict `valid_plant` check MISSED and only per-foot
  contact duty caught (all-six duty is now a gate clause).
  crouchrise2 restored the deployed policy's exact training mix and
  the cheat came back anyway, so the mix-skew theory is refuted and
  the crouch-heavy START DISTRIBUTION itself is the cause. Leading
  mechanism: the BC anchor's reference is clock-indexed from episode
  start, so crouch starts get belly-phase reference poses pushed
  against near-plant states — the anchor actively teaches lifted-leg
  postures, and it bleeds into hold. Two-miss rule: no more mix/coef
  variants; next lever is CODE through spec first — a state-aligned
  (not clock-aligned) BC anchor, or anchor gated off on crouch
  starts. Neither crouchrise checkpoint may be deployed or
  warm-started from; `hard1` stays the stance policy with its known
  0/8 crouch limitation documented.
- **Sim effort realism (parked).** The scary "sim thinks standing is
  free" inversion was a bookkeeping error (units ×18 + wrong pose)
  and is retracted; measured properly, sim overprices effort
  everywhere (safely conservative). Predicting the real ammeter needs
  a command-fight current model — only required if we ever train FOR
  low current.

## What actually made training work

1. **Income gating, not penalties.** Make cheats earn ~zero BY
   CONSTRUCTION. Additive penalties get priced in and paid; every
   time we merely charged for a cheat, the policy paid and kept
   cheating.
2. **BC-anchoring when the reward is right but the trainer can't
   find the motion.** Twice-proven (stand up, hold still). Reward
   tells the policy WHAT is good; it never tells a churning leg which
   WAY to move.
3. **Free structure before compute.** The rot60 wrapper solved
   any-direction walking in an afternoon after four training runs
   (reward variants AND imitation) had failed at it. Check what the
   geometry gives you before asking the trainer to discover it.
4. **Cheap offline tests before expensive training.** The scripted
   reward banks (MDP_PREFLIGHT) prove "honest behavior out-earns
   every known cheat" in minutes, before any launch. Binding rule.
5. **Matched-parent controls.** A run evaluated under an injected
   condition must be compared to its parent under the IDENTICAL
   injection. Several "failures" reversed to PASS (and one "pass"
   reversed) once the control was run properly.
6. **Judge on strict geometry + per-step telemetry, never on the
   training reward.** Climbing reward while the task fails is the
   standard cheat signature (all three GRU runs). Video snapshots
   also miss things: only per-foot contact duty caught the
   crouchrise1 hold cheat and the hold-mode shuffling.
7. **One variable per run; discovery (2M) then hardening (10M).**
   The finishing tails (footprint precision, current spikes) resolve
   with budget; the mechanism has to be proven cheap first.

## Big things we have learned

1. **Reward hacking is the default outcome, not the exception.**
   Every under-specified reward got gamed: freeze-and-collect,
   park-and-earn, flag-leg stands, cadence inflation, the GRU's
   three-legged statue. Countermeasures: income gating + offline
   cheat banks + strict geometric success checks.
2. **Sometimes the reward really is buggy or wrong — so verify the
   reward FIRST, cheaply, and only then stop blaming it.** We
   shipped plenty of genuine reward bugs: the turn-mode kernel paid
   a motionless robot its full walking income (that alone collapsed
   the mirror2 run — freezing literally out-earned walking); the
   sit-down "arrival bonus" paid out without arriving (freeze earned
   +120 until the gate fix); hold pricing paid a parked flag-leg
   EXACTLY as much as an honest stand (a literal tie, proven by the
   bank); and one mechanism bug (the episode-pool restore dropping
   reward state) silently stopped paying the stand-up income at all
   and contaminated three verdicts before it was caught. The point
   is that every one of these is findable in MINUTES, not 20M GPU
   steps: run the offline cheat bank (does honest behavior out-earn
   every scripted cheat under THIS run's exact config?) and, for an
   already-failed policy, the term-by-term income probe (what did
   the bad behavior actually earn, term by term, vs honest and vs
   doing nothing?). Only once those exonerate the reward does the
   rule flip: **a behavior that doesn't change across several
   VERIFIED reward mechanisms is not a reward problem.** Six
   stand-up arms collapsed identically under six bank-checked
   mechanisms — the fix was supervision (BC-anchor), not pricing.
   Four omni-walk arms collapsed under pricing the income probe had
   exonerated (the collapsed policies earned LESS than freezing) —
   the fix was geometry (rot60). Two-miss rule going forward: after
   two same-class failures with a bank-verified reward, change the
   mechanism, never the price or the step count.
3. **Structure is cheaper than training.** The two biggest wins of
   the campaign (rot60, BC-anchor) both bypass discovery instead of
   incentivizing it. Before launching a training arm, ask: does
   geometry, a recorded reference, or the start distribution already
   contain the answer?
4. **Trust only the strictest evidence, and verify before building
   on it.** Training reward lies (cheats). Sparse video lies
   (missed the hold shuffle). Even `valid_plant` lies (missed the
   crouchrise1 parked feet — per-foot contact duty is now a gate
   clause). And one GPU run (`gru-long1`) was launched off a
   training-log claim nobody had checked against the harness —
   invalid evidence, wasted launch.
5. **Robustness was free; stop buying insurance.** 13-for-13
   single-axis sensor/calibration exposure runs bought nothing the
   champion didn't have; the ~20-axis protective sweep on the
   hardware candidate found essentially nothing. Those classes are
   CLOSED — compute goes to capabilities, not more armor.
6. **Hardware truth keeps overturning sim assumptions.** Slip is
   locomotion, not failure; a working gait rocks ±10–20° (a 10° trip
   would kill it); loaded servos respond ~30× slower than the air
   fit; the current "inversion" was our own bookkeeping. Measure on
   the bench, then fix the sim — never the reverse.
7. **Skills interfere under naive mixing; composition works.**
   Quad-hold at any dose erodes walking; the specialist + handoff
   pattern (stand specialist → walk champion → scripted sit) composes
   with zero falls TODAY. The flagship experiment decides whether one
   network can do it all; until it answers, ship specialists.
8. **Wrong logical zeros are how hardware gets destroyed.** The
   08-06 incident came from software poses commanded against a stale
   zero frame — hence the hard safety rules (fresh `set_zero` every
   session, no unsupervised stand/plant blends).

## What happens next

1. **Next bench session** (operator — the critical path; RL walks
   already happened 08-10, see "REAL hardware" above): (a) the
   vref1-r1 vs tip1 A/B on the same floor — compare roll-ramp RATE
   and runaways over several runs, and make sure the policy switch
   actually lands this time; (b) tape-measure an RL walk; (c) first
   hardware runs of the rot60 off-wedge headings and the learned
   stand-up — deploy re-push FIRST (the on-robot stand copy lacks
   its goal profile), fresh `set_zero` always; (d) wz sign audit.
   If tip1 also runs away on this floor, the fix moves to sim: a
   contact/pinning model (no-skate feet), not more DR.
2. **Yesterday's three pending results are all read out** — flagship
   fork CLOSED (MoE refuted by the rise-only control), `gaitbc1`
   FAILED (anchor froze the gait), `crouchrise2` FAILED-mixed (crouch
   fix reproduces, hold cheat traced to the clock-indexed anchor).
   The follow-ups are all spec/code work, not launches: the
   state-aligned BC anchor, the gait reward-accuracy probe, the
   drag-charge magnitude audit, and the P2 structural slip charge
   with its bank.
3. **In flight / queued:** `cw-walk-dragstance1` (hw — the first
   structural per-stance scrape-charge arm, audit-derived size) is
   training. `cw-arch-gru-r4c` finished and FAILED (from-scratch GRU
   closed); `cw-walk-mirturn1` ran and FAILED (mirror training
   closed — wrapper ships). Four-leg walking (weight back, front
   pair as "hands") still needs its spec + bank first — the current
   reward provably punishes exactly that posture.
4. **Track hygiene:** each research line now keeps its own short
   status in `rl_docs/tracks/<track>/STATUS.md` (hw / arch / nobc /
   quad / turn); agent triage stays within a run's track.

Queue and blockers: `RL_PLAN.md`.
