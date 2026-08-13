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

- **OPERATOR RULINGS (08-13 ~12:4x UTC) — five waits DECIDED this
  cycle; full narratives live in the named track docs:**
  1. **hw standing lean → MECHANICAL TRIM** (outside RL; no
     lean-pricing term, no more tipped-exposure/teacher arms;
     bench-session fix). Detail: hw/STATUS.md Now.
  2. **hw walk-takeoff roll → STOP reward/DR sweeps; INSTRUMENT the
     transient, then design a STAGED GAIT-ENTRY TRANSITION**
     (deploy-side entry sequence + sim prototyping; training arms
     only after an instrumented design exists). Detail:
     hw/STATUS.md Now.
  3. **nobc from-scratch gait line → CLOSED; stand-from-scratch
     charter RETAINED** (reopen only on new hardware evidence).
     Detail: nobc/STATUS.md.
  4. **quad → route (2) APPROVED: a feedback/RL rear-four-stepping
     policy is permitted as the quadwalk bank reference, WITH an
     explicit pre-registered ROBUSTNESS GATE** (gate spec is the
     first artifact of the first arm — see the binding conditions
     in quad/STATUS.md). MDP_PREFLIGHT unblocks under those terms.
     **EXECUTED 08-13 ~13:xx UTC:** gate spec committed
     (`rl_docs/tracks/quad/QUADWALK_REF_GATE.md`) and the first arm
     `cw-quadwalk1` is RUNNING (see FLEET line) — no longer a wait.
  5. **watcher idle-kick backoff → APPROVED** (15m→30→60→2h→4h
     no-op spacing, snap-back on real activity, stays live).
- **FLEET: 1/12 pods GPU-training (08-13 ~15:xx UTC: `cw-quadwalk3`
  FAIL — fronts-down cheat a THIRD time with the lift-contact charge
  verifiably live (−1.54/tick ≈ −575/ep, ~40% of return, simply
  paid): PRICING is a measured-exhausted lever class for quadwalk;
  per the pre-registered false branch the blocker is EXPLORATION
  from the six-foot plant spawn. CODE lever landed same cycle
  (`goal.quadwalk_start="quad"`: episodes spawn already in the
  four-leg stance, tilt refs level, 25° envelope for the ~16°
  limp-settle sag; default bit-exact, bank 87 green, commit e208b86)
  and **`cw-quadwalk4` is VERIFIED RUNNING on train-0**, 2M
  discovery, one lever package vs quadwalk3. Backlog empty;
  train-11's idle CPUs still run the dynrep pilot replication, GPU
  free; see the dynrep entry).** Every OTHER idle slot maps to a
  named wait below.
  ~~ASSUMPTION (operator to review, 08-13 ~12:0x)~~ **APPROVED by
  operator ruling above:** idle-kick BACKOFF stays — five deep-model
  idle-kick cycles in 80 min (10:37–11:58 UTC) each re-verified this
  same unchanged, fully operator-gated board; at the 96/day cap
  that's ~$1k+/day of no-op deliberation (08-09 cost order).
  Consecutive no-op kicks space out 15min→30→60→2h→4h (capped);
  cadence snaps back to 15 min on ANY real activity (finished run,
  training run, checkup findings, operator `ops.sh cycle`). Not a
  disable: the watcher still kicks at least every 4 h, and
  triage/drain/checkup paths are untouched. No unattacked sim
  stand/walk blocker remains: the one-parked-foot hold and det
  flat-rise stall are SOLVED (footlow2-hard1), the crouch-splay
  tall-walk wall is BROKEN (bcgait1-hard1), contact/pinning + warp
  physics are audited clean, and the two open transients (takeoff
  roll, standing lean) are DECIDED per the rulings above.
- ~~hw — standing-lean design fork~~ **DECIDED 08-13 ~12:4x UTC
  (ruling 1 above): mechanical trim, outside RL.** The remaining
  work is a bench item (trim/zero-calibration/shimming), folded
  into the bench-session list below. Detail: hw/STATUS.md Now.
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
- ~~hw — walk-takeoff roll transient: operator design discussion~~
  **DECIDED 08-13 ~12:4x UTC (ruling 2 above): no more reward/DR
  sweeps; instrument the takeoff transient, then design a staged
  gait-entry transition.** This is now NAMED agent-doable work
  (instrumentation of bench tapes + sim replays of the first
  ~1.5 s, then a deploy-side staged entry sequence prototype) —
  not a wait. Detail: hw/STATUS.md Now.
- **multitask — PAUSED by operator (08-13 ~12:2x UTC), direction
  call withdrawn.** Operator is prioritizing the dynrep
  (world-dynamics) line instead. Do not launch, queue, or plan
  further `cw-mt-` arms until the operator unpauses. The wave-1
  read stands as recorded (a2 pass; b2 acquisition shortfall; c2
  fail; capacity/staged-widening/history levers all closed);
  `eval_cmd_suite.py` remains available to other tracks. Detail:
  multitask/STATUS.md.
- **arch — DAgger rise redistillation LANDED on the operator's Mac
  (08-13 ~13:05: rise is in the BC init for the first time, det
  3/12 real wins, hold retained; COST: lower collapsed 0/6) but the
  artifact `ppo_goal_cw_gru_dual_bc_dagger1.zip` (md5 b5167c10) is
  LAPTOP-LOCAL — not on the controller/pods, so no arch arm can
  warm from it (wait since 08-13 ~14:xx: checkpoint push).** Also
  open: the operator's recorded a/b call (accept as-is and let
  RL+anchors rebuild lower, vs a rise-only-DAgger variant distill).
  Recommendation on file if assume-and-go applies once the zip
  arrives: (a) accept — dual1's RL+anchors already rebuilt lower
  6/6 from a weaker init. Detail: arch/STATUS.md.
- ~~nobc — close the from-scratch gait line?~~ **DECIDED 08-13
  ~12:4x UTC (ruling 3 above): CLOSED; stand-from-scratch charter
  retained.** Reopen requires new hardware evidence. Detail:
  nobc/STATUS.md.
- ~~quad — MDP_PREFLIGHT ruling needed~~ **DECIDED 08-13 ~12:4x UTC
  (ruling 4 above): feedback/RL rear-four stepping PERMITTED as the
  quadwalk bank reference, with an explicit pre-registered
  robustness gate.** The gate spec (multi-seed det, DR panel, zero
  falls, fronts-lifted + no-credit verification, stillness bar) is
  the FIRST artifact before any arm launches — binding conditions
  in quad/STATUS.md. Quadwalk is now launchable under those terms
  (excess-capacity priority rules still apply; hw keeps pod
  priority).
- ~~turn — MirrorPolicy deploy port~~ **CLEARED 08-13 (operator
  session, 08-12 night): the port LANDED** — `run_policy_move(...,
  turn="left"/"right"/"hold")` + rot60 composition in
  `linux_control/rl_policy.py`, `POST /api/rl/walk {"turn": ...}`,
  mirror.py in both deploy scripts, `tests/test_mirror_runner.py`.
  Remaining turn work is a bench session (below; re-deploy first).
  Detail: turn/STATUS.md.
- **dynrep — pilot seed replication RUNNING on train-11 idle CPUs
  (since 08-13 ~12:3x UTC; waiting on the pod job, hours-scale).**
  The operator's push (4d26954, 08-13 12:12 UTC) CLEARED the old
  code wait. Datasets/models stayed laptop-local (gitignored), so
  the pipeline regenerates the v2-recipe dataset + obs encoder on
  the pod (artifacts named `*v2pod*` so they can't be confused with
  the laptop's; G1/G2 gates enforced before any PPO wiring), then
  runs the A/B/C pilot cohort for seeds 1–3 in parallel (s0 = the
  operator's laptop pilot; NOT pooled — different encoder
  provenance). Log: `rl_move/dynamics/logs/pod_pilot_rep.log` on
  train-11 (`pod_pilot_rep.sh`). Known recipe drift: the noslip
  actor's 10% share falls back to tripod (noslip_gait.py is
  laptop-only; collect.py now degrades gracefully). Health-checked
  08-13 ~13:19 UTC (operator-kick cycle): encoder pretraining
  ~25k/40k, trainer at ~18.5 cores, healthy — PPO cohort still
  ahead, hours-scale. Next cycle to see it finished: triage as a
  direction-of-effect check against the operator's laptop 3-seed
  sweep (30ca480 verdict revision: better-final YES, faster/
  retention NO; expected ordering in dynrep/STATUS.md), then launch
  the hold->walk pair — its code landed 08-13 ~13:3x (walk task +
  eval-every<=10k + seeds 1–5 runner `pod_holdwalk.sh`, smoke-tested;
  launch-blocked ONLY on the rep triage per operator ordering). GPU
  on train-11 stays free.
- **Bench session items (operator time, not GPU — nothing is
  deploy-blocked):** first hardware run of the learned stand-up
  (deploy re-push DONE + HTTP-verified 08-11 ~21:15, goal profile in
  the meta), rot60 off-wedge headings, the vref1-vs-tip1 A/B on one
  floor, tape reading on an RL walk, **mirror turn session
  (turn=left/right/hold — re-deploy the board first: new
  rl_policy.py + mirror.py)**, and **the standing-lean mechanical
  trim (per ruling 1)**. Turn-sign audit CLOSED (signs match both
  ways). Session runner: `rl_move/scripts/bench_blast.py --go`.

- **UPDATE (08-12, hold/rise pricing-only levers now ALL closed):**
  the contact/pinning code-wait cleared earlier (belly/tucked-shank
  collision built and falsified — the recorded curls never touch the
  chassis; the real mechanism is the rise ending on a 3-foot,
  ±25mm-flickering knife-edge that sim survives and hardware doesn't).
  `cw-stand-margin1` (paying for CoM depth inside the support
  polygon) and `cw-stand-transdrag1` (charging loaded-foot scrape
  during stand/sit) both FAILED — margin1's own target stat never
  moved (BC-anchor-pinned) and BOTH runs independently reproduce the
  identical hold one-foot park (idx1, duty 0.03-0.05) that closed
  `cw-stand-minfeet1` a few hours earlier. **Three independent
  reward-side arms (minfeet1, margin1, transdrag1) now confirm the
  SAME closed door: no more pricing-only levers on an anchored stand
  mode.** `cw-stand-riserock4` (last rise-rock DR variant) also
  FAILED via the same outrigger cheat. **CLEARED (08-12 ~09:5x, same
  cycle as the margin1/transdrag1 verdicts): the anchor-side
  spec/verify pass RAN, and the answer is neither of the two
  theories on the board.** (a) `_q_nom` is exonerated: 48/48 hold
  resets settle with ALL SIX feet firmly loaded (3.2–3.6 N, none
  under 0.5 N) — the anchor reference is a genuine six-foot stance
  (though feet 1/4 ARE the two lightest at settle, matching which
  foot every park has ever chosen). (b) "PPO defies supervision" is
  wrong too: the parked policy's per-leg anchor loss on the parked
  leg (0.0032) is byte-comparable to the clean parent's same leg
  (0.0031) — **the park is INVISIBLE to joint-space action MSE**,
  because a millimetre-scale contact break needs only fractions of a
  degree of hip lift (3 dims in 18, diluted to ~1e-4). Fix landed
  same cycle: `train.bc_anchor_foot_z` — a foot-HEIGHT-space anchor
  term (differentiable FK twin of body_ik, default off, bit-exact
  off, 3 new tests + full semantics bank green) under which a 10 mm
  commanded hover costs ~1.0 instead of ~1e-4. **RESULT (08-12):
  `cw-stand-footz1-r1` PASS (partial) — the fix WORKS.** Det hold:
  ALL SIX feet duty 0.92–0.98 in every one of 6 episodes (the frozen
  parent scores 0.05 on the same leg in the identical test) — the
  first clean six-foot det hold after 6+ straight pricing-arm
  failures, video-confirmed. Two minor misses, both at/near the
  parent's own rate and not park-related: sto hold 4/6 valid_plant
  (current-spec, not duty), det rise 5/6 vs parent's 6/6 (one
  flat-start height miss, zero falls). Lower unchanged (matches the
  parent's own pre-existing 3-leg-proud pattern exactly, confirmed
  not new). **UPDATE (08-12): `cw-stand-footz1-hard1` (the 10M
  hardening) FINISHED — FAIL.** Hold now survives hardening cleanly
  (det+sto all-six-feet duty 0.92-0.99, matching/beating discovery),
  but lower REGRESSED from the ~4/6-matching-parent baseline to 0/12
  both passes — the SAME known three-leg outrigger cheat, more
  entrenched under the extra budget (clearances up to 170mm). Root
  cause: this lineage never got the lower-mode BC anchor that a
  sibling branch (`cw-stand-anchormix1-r1`) already used to solve
  lower cleanly (6/6) — the two fixes were never combined. `hard1`
  (`holdbc1_hard1`) stays deployed. **UPDATE (08-12 midday):
  `cw-stand-footlow1` (the combination arm) FINISHED — FAIL on its
  own gate, but the merge is ADDITIVE on two of three modes: first
  policy ever with a clean six-foot hold (det duty ≥0.94 every
  foot) AND 12/12 lower with feet ending flush (sub-mm clearances;
  parent was 0/12 at up to 126mm). The cost surfaced in RISE:
  det 3/6 / sto 2/6, stalling belly-down ~100mm short — the
  anchormix lineage's known det flat-rise stall, carried in by the
  merge. **WAIT CLEARED (08-12, same day): the alignment audit RAN
  (`probe_anchor_align.py` on the live stalled policy) and found the
  mechanism — a PLATEAU FIXED POINT: the recorded demo crawls
  0→25 mm over 5+ s, so the anchor's half-second-ahead target at the
  stalled belly state commands only 1–5 mm of height gain, servo lag
  cancels it, and the policy follows its supervision perfectly (its
  anchor error is LOWEST during the stall — the anchor was teaching
  the stall, not blind to it). Fix landed + tested
  (`train.bc_anchor_min_h_ahead_mm`: the aimed-at demo frame must be
  ≥15 mm above the robot's current height); the one-variable retry
  `cw-stand-footlow2-r1` trained.**
  **RESULT + NEW WAIT (08-12 midday): `cw-stand-footlow2-r1` FAIL
  per its own gate, but the floor mechanism WORKS — the det flat
  stall moved from ~100 mm short to 15–16 mm short, and noisy-mode
  rises now succeed 6/6 including every flat start (was 2/6). Two
  residuals block the next arm, both flagged for a DEEP DIG-IN
  (waiting on that cycle since this one): (a) the exact-mode rise
  ends 15 mm short only on the eval's seeded flat starts (a probe
  from a different start reaches 3 mm error with the anchor
  correctly aiming at the demo's final plant frame) — need the
  seeded audit before choosing a lever; (b) the stronger rise
  supervision re-opened the hold one-foot park (foot idx1 duty 0.03
  all 6 det episodes) DESPITE the foot-height anchor that fixed it —
  the rise/hold seesaw is real and unpriced. Sit-down stayed 12/12.
  `holdbc1_hard1` stays deployed.**
  **CLOSED (08-12 midday): the session-profile ramp-jitter axis**
  (`cw-stand-rampjit1`, the 08-11 model-tour follow-up) — FAIL per
  its own pre-registered gate: the interactive-session rise still
  misses the bar (59.5 vs 60 mm @9.5 s; parent 55) and sit-down
  retention regressed (det 2/6, sto 0/6, outrigger class). One real
  positive for the record: the parent's deterministic
  sit-after-walk TIP-OVER did not occur (session no_falls +
  sit_descends PASS). Per the gate, next lever is START-STATE
  exposure, not more profile jitter — unspec'd, folded into the
  same stance-line wait above.
  **Still WAITING (walk side): the takeoff-roll transient for
  WALKING has no launchable lever** — torque/command DR families all
  closed, and margin-style pricing (the hoped-for generalization) is
  now refuted on the stand side too. Walk-takeoff needs an operator
  design discussion or the same anchor-side investigation once it
  exists. Nothing is training against the walk-takeoff blocker.
- **CLEARED (08-12 ~16:1x, was WAITING): the "needs a probe that
  FORCES a tipped spawn" design fix landed with ZERO new code** —
  `dr.tipped_start_prob`/`dr.tipped_start_deg` are existing cfg keys
  that apply as absolute overrides AFTER dr-scale (`sim_env.py`
  reset), so `--dr-scale 0.0 --cfg-set dr.tipped_start_prob=1.0
  --cfg-set dr.tipped_start_deg=8,8` forces every hold episode
  tipped 8° with every OTHER DR axis isolated off — no launcher, no
  training. Ran on both footlow2-hard1 and -stable1 (12 det + 12 sto
  hold episodes each): the policy ALREADY partially self-corrects
  (roll settles ≤2.6° in 11-12/12 episodes, classed
  recovered/settled) but often misses the strict valid_plant spec on
  final HEIGHT (15–31mm over the 15mm bar, one episode also
  over-current) — valid_plant only 5/12 det, 9/12 sto on BOTH
  checkpoints, near-identically. So `cw-stand-footlow2-level1`'s
  FAIL is re-attributed: its 3-variable confound (dr-scale 0.35 +
  ground_tilt 5° + tipped_start 0.30 in one run) — not the
  tipped-start axis itself — is the more likely cause of the
  reopened park. **Refilled with the one-variable isolation this
  should have been:** `cw-stand-footlow2-tip1` (2M discovery, warm
  from hard1, dr.tipped_start_prob=0.5/deg=6-10 ONLY, dr-scale 0.0,
  everything else byte-identical to hard1) — gate: forced-8°-tip
  valid_plant ≥9/12 each pass (vs the probe's own 5/12 det, 9/12 sto
  baseline) + zero new foot-duty park + clean nominal retention.
  `footlow2-stable1` PASSED its own gate this cycle (see Now/RISE.md)
  — a second stance candidate, real hold-drag tradeoff vs hard1
  (+75%), does not strictly dominate it.
  **RESULT (08-12 eve): `cw-stand-footlow2-tip1` FAILED both
  pre-registered clauses — the tipped-start DR axis is CLOSED as
  HARMFUL on anchored stance.** Training at 50% tipped spawns taught
  the policy to LIVE TILTED, not to level: the forced-8° probe holds
  height (det valid_plant 12/12 vs parent 0/12) but never levels
  (roll tail med 7.2°, settled 0/12 vs parent 11/12) with a foot
  parked every det episode; worse, NOMINAL retention broke — untipped
  det hold ends tilted 7.6° and the standard eval logged 6 tilt_roll
  falls (parent: zero, everywhere). Per the gate's own consequence
  clause the anchor is implicated: no further isolated-DR retries on
  this lineage. Tip robustness, if hardware demands it, needs an
  anchor-side design (tip-aware reference), not a DR knob. The
  stance candidates stand unchanged (hard1 / stable1).
- **CLEARED (08-13 ~01:xx, was WAITING since 08-12): nobc's
  scheduler code-wait is closed — the in-run coefficient scheduler
  LANDED and its first arm is training.** `sched.*` cfg keys ramp
  one coefficient by global env steps during a run; implemented in
  `sim_env._step_begin` so both trainer stacks get it by
  construction; default off = bit-exact, 10 new tests
  (`test_coef_sched.py`) + the full semantics bank green, REWARD.md
  row added. `cw-gait-sched1` (2M discovery, from-scratch on the
  dragstance1 stack, k_drag_stance ramped 0→8000 over steps
  0.5M→1.5M — paddle first, then price the skate away) is the LAST
  untried form of GAIT P3 lever 2; pre-registered: if it produces
  the freeze OR the unresolved-charge skate again, the from-scratch
  gait line has no levers left and the recommendation to the
  operator is to close it.
- **CLEARED (08-12 ~22:0x, was WAITING on the 20M re-queue): the
  multitask wave-1 read is COMPLETE and CLOSED** — `cw-mt-a2`
  specialist control PASS (real six-leg gait, prog med 1.23-1.30),
  `cw-mt-b2` narrow generalist FAIL (real gait but short on
  speed/yaw), `cw-mt-c2` broad generalist FAIL (flag-leg, falls
  19/24): command-width interference is real and monotone at a
  matched 20M budget. The follow-up capacity probe
  `cw-mt-b-arch256-1` (256×256 fresh at 2M) also FAILED its gate —
  width is not the lever. **`cw-mt-widen1` (staged widening, 2M)
  FAILS(acquisition) but CONFIRMS the walking prior fully survives
  command widening** (gait_valid 6/6 det, prog med 1.57 vs a2's
  1.23, zero sacrificed legs, roll_tail flat-to-better than a2) —
  neither new command (stop/yaw) is acquired yet, but no mt arm has
  ever acquired a command at only 2M, so this doesn't yet separate
  "needs more budget" from "can't represent it". Now training:
  `cw-mt-widen2` (train-0, same recipe continued to the b2-matched
  20M) to settle that before reaching for the representation lever
  (obs history). Detail: `rl_docs/tracks/multitask/STATUS.md`.
- **CLEARED (08-12, was WAITING): the mode-gated dual-core GRU
  (`DualGruActorCriticPolicy`, commit 2137c00) landed and the answer
  is in.** `cw-arch-gru-dual-scratch1` (2M, from-scratch + full
  anchor stack on the dual arch) FAILS its own gate on one narrow
  clause (rise sto 2/6 vs the >=3/6 bar, n=6 — det rise unchanged at
  parent's 1/6) but DECISIVELY confirms the central question:
  splitting locomotion/stance into separate cores removes the
  shared-trunk interference — det walk gait_valid 6/6 with ZERO
  sacrificed legs (parent scratch-anchor1: 0/6, one leg parked in
  every episode), hold/lower both hold at parent's 6/6, anchor loss
  converges clean (~0.01). New residual to watch, not gate-breaking:
  under own-DR 0.5 the leg-sacrifice partially reappears (gait_valid
  3/6 vs parent's 5/6). **CLEARED (08-12): `cw-arch-gru-dual1` (10M
  hardening) FINISHED — the walk-freeze question is answered YES.**
  Det walk gait_valid 6/6, zero sacrificed legs, prog_ratio 0.95
  (parent anchor3: 0.03, pixel-static) — real translation confirmed
  on video. Hold/lower det 6/6 each, with BETTER drag/roll-tail than
  the shared-trunk parent (hold drag 55mm vs 117mm; lower 99mm vs
  310mm). Fails its pre-registered n=6/seed=0 gate draw by one
  episode on rise (1/6, needs >=2/6) — but a same-cycle n=12 recheck
  found 7/12 (58%, incl. real non-crouch wins), so the small first
  draw was noise, not a true deficiency; rise is much closer to
  solved than the gate letter shows. Mode-gated dual-core routing is
  now the confirmed fix for the arch line's shared-trunk walk-freeze;
  not yet formally re-passed as a full-skill candidate. **Follow-up
  `cw-arch-gru-dual-hfloor1` FINISHED — FAIL, and informative: the
  MLP lineage's plateau-fix lever (aim the rise anchor >=15mm above
  current height) does NOT transfer here.** A fair larger-sample
  recheck (n=12, matching the method that corrected dual1's own
  noisy draw) finds rise WORSE, not better (5/12 det with zero
  non-crouch wins vs dual1's 7/12 with two; 1/12 sto vs dual1's
  4/12), plus a new pathology — 3-4 non-crouch attempts now trip an
  over-current shutdown from straining in a stuck low crouch for the
  full episode (video-confirmed honest stall, not a cheat). Walk/
  hold/lower all held clean, hold/lower slightly BETTER than dual1's
  own numbers. Conclusion: this architecture's rise gap is data-
  poverty in the BC-distill (never enough real rise demos), not a
  supervision-aim problem — the lever family is closed here; the
  live next step is the operator's in-progress DAgger rise
  redistillation (arch/STATUS.md "Next").
- **UPDATE (08-12 ~23:1x): `cw-mt-widen2` (multitask staged-widening,
  budget-matched 20M) FINISHED — FAIL(no-acquisition), decisively.**
  The walking prior survives the widened command set perfectly at
  the full 20M budget (gait_valid 6/6 det+sto both DR passes, zero
  terms, roll_tail 0.4-1.0°) but neither stop nor turn is acquired
  (signed-probe stop-hold speed 0.0417 m/s vs fwd-hold 0.0688, needed
  <=0.02; tip-yaw differential 0.0032, needed >=0.10) — this closes
  the budget question the widen1→widen2 pair was designed to answer:
  20M is not a too-short fine-tune, the staged-widening budget lever
  is dead. Refill hit a documented infra gotcha (hist16+model-DR
  `/dev/shm` cap, 0-step SIGBUS) that a concurrent cycle fixed and
  requeued as `cw-mt-b-hist16-r1`, now RUNNING (train-0) — the
  representation lever. Detail: `rl_docs/tracks/multitask/STATUS.md`.
- **UPDATE (08-12 ~23:3x): `cw-mt-b-hist16-r1` (multitask
  representation lever, 2M) FINISHED — FAIL per its pre-registered
  gate.** 16-frame history does not change 2M discovery on b1's
  recipe: gate(DR0) det prog med 0.21 vs the 0.32 bar (b1 baseline
  0.16, delta inside noise), gait_valid 0/6, same low-crouch splay
  video-confirmed. This closes the cheap-2M-probe menu for the track
  (capacity/arch256, staged-widening/widen1-2, and now history all
  FAIL at 2M or fail to acquire commands even with a surviving
  walking prior at 20M). Refill: `cw-mt-b-hist16-20m1` (same recipe,
  b2-matched 20M budget — the real command-acquisition test) is
  RUNNING (train-0). Detail: `rl_docs/tracks/multitask/STATUS.md`.
- **UPDATE (08-13 ~00:3x): `cw-mt-b-hist16-20m1` (the real 20M
  command-acquisition test for history) FINISHED — FAIL(worse/no-gait),
  decisively.** gait_valid collapses to 2-4/6 across all four passes
  vs `b2`'s clean 6/6, driven by a front leg chronically near-frozen
  (duty 0.01-0.17 in every one of 24 episodes, video-confirmed) —
  worse than `b2`'s already-marginal weak leg. Progress/slip numbers
  look flat-to-better but that's a drag-exploit artifact (the other
  five legs dragging the near-frozen one), not real improvement; roll
  stays flat-to-worse. History (16-frame) is now closed as a lever at
  BOTH budgets tested (2M and this 20M budget-match) — no further
  hist-frames variants. **The multitask track's entire cheap-lever
  menu for the wave-1 acquisition shortfall (capacity, staged-
  widening, history) is now exhausted; every lever FAILED or made
  things worse.** WAITING-ON: an operator call on the next direction
  (transplant the arch track's recurrent architecture onto this
  recipe, vs. narrow the command-width curriculum, vs. accept `b2` as
  this recipe's ceiling) — no further isolated-lever retries queued
  pending that call. **UPDATE (08-13): the transplant's CODE is now
  built and tested** — `obs.mode_onehot_cmd=1` (walk_task) derives the
  dual-core GRU's routing one-hot from the LIVE blended command
  (stopped ⇒ stance core, moving ⇒ locomotion core), so
  `DualGruActorCriticPolicy` drops onto the command-conditioned
  recipe unchanged (`--gru-dual` + `--cfg-set obs.mode_onehot=1
  --cfg-set obs.mode_onehot_cmd=1`; default OFF = bit-exact legacy
  obs, `tests/test_mode_onehot.py`). The per-command eval runner the track
  spec calls for also landed: `rl_move/sim/eval_cmd_suite.py` (exact
  (vx,vy,wz) triples — `--cmd` repeatable / `--suite` JSON / default
  panel; per-command tracking/falls/progress/slip/current, det+sto,
  JSON `--out`). NOTE: the landed version is MLP-only — a laptop
  variant with GRU/dual-GRU checkpoint loading sits unmerged at
  `eval_cmd_suite.laptop-20260812.py`; that port is needed before
  the transplant's per-command gate can run on a dual-core
  checkpoint. The operator call is otherwise a launch decision.
  Detail: `rl_docs/tracks/multitask/STATUS.md`.
- **Fleet at ~01:3x UTC 08-13: 0/12 pods training** —
  `cw-gait-sched1` (nobc) FINISHED and FAILED (see the WAITING entry
  above); backlog is empty (`capacity.py` confirms 12/12 free, no
  drain-bug). All 12 idle slots are now named waits, none an
  unattacked blocker: multitask's lever menu is exhausted pending the
  operator call above; nobc's is exhausted pending the physics-easing
  build-or-close call above; the other tracks' waits (below) are
  unchanged from the prior fleet-state note and were re-checked this
  cycle, not stale. (Earlier note, superseded: at ~01:xx the fleet was
  1/12 with `cw-gait-sched1` running on train-0.) The wave-1 20M re-queue, the arch256 capacity
  probe, the widen1/widen2 staged-widening pair, and the hist16-r1/
  hist16-20m1 history pair are all verdicted (a2 PASS control; b2/c2
  FAIL — width interference; b-arch256-1 FAIL — capacity not the
  lever; widen1 FAIL(acquisition)/widen2 FAIL(no-acquisition) —
  walking-prior survival confirmed but budget doesn't teach new
  commands; hist16-r1/hist16-20m1 FAIL/FAIL(worse) — history isn't
  the lever at either budget). All earlier finished-but-unverdicted
  runs are verdicted (getup4 FAIL/pricing-refuted; footzsharp1
  PASS/hover-lever; footlow2-tip1 FAIL/tipped-DR-closed-harmful;
  mt-a1/b1/c1 FAIL-budget). Why the other 11 pods idle, per track:
  hw stance — two passing candidates, promotion is a BENCH call
  (operator); hw walk — bcgait1-hard1's path to Gate 0 is bench tape
  evidence (operator), takeoff transient still needs the
  contact/pinning design discussion (below); arch — waiting on the
  operator's in-progress DAgger rise redistillation; nobc —
  gait-from-scratch's last lever (physics easing) was unbuilt code at
  the time; built+tested later on 08-13 (see the UPDATE below); quad —
  four-leg-walk reward spec+bank FIRST (specification, never trains);
  turn — MirrorPolicy deploy port was robot-runner work; landed 08-13
  (see the UPDATE below), bench session pending.
- **WAITING (since 08-13 ~01:2x): nobc's gait-from-scratch line —
  `cw-gait-sched1` (the in-run coefficient scheduler's first and only
  arm) FAILED, the pre-registered false branch exactly (det fwd
  travel 0.01m vs the 0.3m bar, slip/m 9.4/18.4 vs the 3.0 bar,
  frozen-stance video, unresolved drag charge despite the ramp firing
  correctly).** This closes GAIT P3 lever 2 in every form tried
  (fixed rung, warm-start anneal, true in-run schedule); the whole
  no-new-code lever menu (2, 4, 5) for nobc gait-from-scratch is now
  exhausted. The only remaining lever (physics easing: relax
  gravity/servo-velocity-ceiling early, anneal to nominal) is genuine
  UNBUILT CODE — it needs new per-episode-reset plumbing in
  `domain_rand.py`, code shared by every run in every track, so it
  was NOT written this cycle next to a live triage (exactly the kind
  of rushed shared-code change that produced past pool-restore/
  dilution bugs). Blocked on: an operator call to either dedicate a
  cycle to building+testing physics easing, or accept the
  from-scratch gait line as exhausted for now (does not block the hw
  mainline — BC-init already solved tall walking there). **UPDATE
  (08-13): physics easing was BUILT, tested, RUN — and its arm
  FAILED.** `ease.gravity_scale` / `ease.vel_ceiling_scale` landed
  in `sim_env._reset_begin` (snapshot e40a3ea), scaling the
  per-episode DR draw (`_ep_rand`) both trainer stacks already
  consume (C-path `apply_to_model`, MJX device rows) with zero new
  `domain_rand.py` plumbing; both keys re-read every reset so the
  existing `sched.*` engine anneals them in-run. Default OFF is
  bit-exact legacy (`tests/test_physics_ease.py`, 8 green; sched +
  full semantics bank green). Its one arm `cw-gait-ease1`
  (half-gravity annealed 0.4M–1.1M, otherwise byte-identical
  dragstance1 stack) FAILED the pre-registered false branch — the
  identical freeze even at half gravity — so P3 levers 1–5 are ALL
  closed and the from-scratch gait line is out of levers; the CLOSE
  recommendation is an operator call (see the Now section above).
  Detail: `rl_docs/tracks/nobc/STATUS.md`, `rl_docs/GAIT.md` P3.
  (A parallel laptop reimplementation of easing — `ease.scale` /
  `ease.servo_vel_scale`, `test_phys_ease.py` — was superseded by
  the e40a3ea version and discarded in the 08-13 merge resolution.)
- Operator-gated (bench, not GPU): NOTHING is deploy-blocked anymore.
  The deploy re-push is DONE and verified over HTTP (08-11 ~21:15):
  the robot's ACTIVE stance policy is stand_holdbc1_hard1 WITH the
  trained goal profile in its meta (stand 5s hold / 6s ramp /
  +111mm; lower 1s/5s/−45mm) — STAND is no longer profile-stale.
  The turn-sign audit is CLOSED (operator 08-11 night: the robot
  turns the way the drawn signs say, both directions — no bridge
  flip needed; rate unmeasured). Remaining bench items are session
  work when the operator wants them: first learned stand-up (hand
  ready, belly start + fresh set_zero — preflight currently refuses
  from the tilted rest pose, as designed), rot60 off-wedge headings,
  the vref1-vs-tip1 A/B, RL-walk tape. Bench turn sessions wait
  only on the MirrorPolicy deploy port [CODE]. **UPDATE (08-13): the
  deploy port LANDED** — `run_policy_move(..., turn="left"/"right"/
  "hold")` in `linux_control/rl_policy.py` (mirror wrapped OUTSIDE its
  own rot60 instance; heading-hold bang-bang on integrated gyro z,
  4° hysteresis, per the sim probe), exposed through
  `POST /api/rl/walk {"turn": ...}`; `turn` unset is bit-identical to
  today's walk path. mirror.py ships in both deploy scripts;
  `tests/test_mirror_runner.py` locks the port (replay parity vs the
  mirror primitives, selector semantics, numpy-only import chain).
  Bench turn sessions now wait only on an operator session (re-deploy
  first — the board needs the new rl_policy.py + mirror.py).

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
