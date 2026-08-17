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

**OPERATOR RULING 08-17 (~18:05 UTC) — SIM SPRINT:** the robot is
off the bench for about a day of repair. Until the operator says it
is back, the campaign's single deliverable is **reliable rising +
walking in the MuJoCo sim, download-ready** — every cycle keeps a
concrete answer to "what would we download tomorrow morning?"
(named checkpoints + gate evidence). Known gaps to attack first:
post-lower rise, takeoff roll transient. No new research-track
launches unless they directly serve this; bench-owned items stay
parked. Full text: RL_PLAN.md "SIM SPRINT" + CURRENT_TRUTHS.md.
**The concrete download answer is written and maintained at
`rl_docs/DOWNLOAD_ANSWER.md`** (08-17: the hierarchical composition —
stance `footlow2_hard1` + walk `bcgait1_hard1` + session controller
with entry-slew and STOP→stance-hold — det 0.967 / sto 0.853 on the
n=600 held-out session gate; single weak boundary = post-lower rise).

**Last updated: 2026-08-17 (dynrep: the joint PPO+auxiliary rebuild —
the operator-directed third attempt to make the pretrained dynamics
transformer help walking — FAILED its pre-registered 1M gate on all
three conditions, and the line STOPS adding complexity per that gate;
scratch PPO remains the best walker in every dynrep cohort to date.
Separately, all three C arms were killed by a leftover memory-watchdog
during checkpoint saves because checkpoints were pickling the 12.5GB
rehearsal corpus — serialization + bookkeeping bugs fixed and tested,
every artifact preserved, no relaunch by operator order. Detail:
dynrep/STATUS.md + WAITING-ON below.) Earlier 08-15 (arch: a small causal-transformer policy
trunk now WALKS as well as the flatten-MLP champion at the same 40M
step budget — zero falls, clean six-leg gait, no roll-fall — the
first architecture-line proof that attention-based trunks aren't a
dead end for this robot, walk-only, not deployment-contract-ready.
`cw-arch-tf-r1-hard1`; detail: arch/STATUS.md.) Earlier (hw: the
post-lower stand-up mystery is
SOLVED — the c3 collapse was a taught behavior, not a learning
failure. The in-context sequence trainer's rise reference starts at
belly height, so it paid the robot to flop back onto its belly and
redo the flat stand-up after every sit; held-out sessions then stall
over-current on more than half of deterministic post-lower rises.
The one-line schedule fix ("stand up from where you are") is coded,
tested and snapshotted, and `cw-stand-postlower4` is training on it
against a fresh pre-registered 600-session cohort (c4). Product
baseline unchanged. Details: hw/STATUS.md + SESSION_BULK_GATE.md.)
Earlier (arch: operator directive
fb_20260815T013349_488ffd executed — the four-expert fully isolated
one-checkpoint architecture (per-expert actor/critic GRUs, heads,
log_std; zero-init transition adapter) is built, tested and
snapshotted; Arm A teacher-distill is running on train-1 CPUs and
Arm B's from-scratch 2M mechanism canary is training on train-0;
staged full-budget follow-ups pre-registered in
`rl_docs/tracks/arch/MODE_EXPERTS_DIRECTIVE.md`. Multitask pause
lifted BY THE OPERATOR for these two arms only; the hierarchy stays
the product baseline.) Earlier (hw: the named next arm is no longer
"to spec" — `cw-stand-postlower3` is RUNNING: an idle-kick cycle built the
stance-only in-context sequence trainer (`goal.mode_seq_stance`,
default-off, tested, snapshotted), pre-registered its bulk gate
(Cohort c3, fresh banks) and launched the 2M discovery arm on train-0.
Details: WAITING-ON FLEET entry below + hw/STATUS.md.) Earlier 08-14
(late — hw: the post-lower stand-up saga
took a decisive turn: `cw-stand-postlower2` (the low-dose retry)
FAILED, and the dig-in proved the whole bank-exposure family was
training the robot to chase a MECHANICALLY IMPOSSIBLE height — the
harvested sitting poses rest ~5cm higher than the flat belly the rise
target is calibrated against, so the goal asked for a stand ~5cm
TALLER than the robot can be; straining at max current was the
correct answer to a wrong question, which is why postlower1 got
WORSE. The goal-anchoring fix is written, tested and snapshotted
(default-off), and with it the champion gets its first-ever real
stand-ups from harvested poses — but a cold spawn still can't
reproduce the in-session context (the champion collapses to belly
deterministically), so the next arm (`cw-stand-postlower3`, to spec
next cycle) trains the transition IN CONTEXT with lower→rise
sequence episodes instead of cold teleported starts. Product
baseline unchanged. Chain: hw/STATUS.md.) Earlier ~22:5x UTC — hw: the first fix attempt on
that named POST-LOWER boundary (`cw-stand-postlower1`, training the
stance policy on 35% harvested post-lower start poses) FAILED, and
FAILED backwards: a full 600-session bulk re-read shows stochastic
post-lower rise got WORSE (0.801→0.717, a real regression, not
noise), plus small hits to det session zero-fall and cold-start rise.
No exploit — video shows a genuine over-current stall from the deep
bank pose, the same failure mode as before, just more often. A
cheaper 2M-step follow-up (`cw-stand-postlower2`, exposure cut to
15%) is running now to tell dose from mechanism before any reward
change. The product baseline is UNCHANGED (still the hierarchy
below); full story: `rl_docs/tracks/hw/SESSION_BULK_GATE.md` "Cohort
c2".** Earlier ~21:4x UTC — hw: the joystick session
story now rests on BULK, HELD-OUT numbers instead of 12 repeated
cases, per the operator's evening directive: a new resumable sharded
session evaluator ran 1,800 fresh ~60 s randomized joystick sessions
(300 deterministic + 300 stochastic per candidate, matched schedules,
never-before-used seeds, 11 idle pods' CPUs, ~3 minutes) comparing
the hierarchical specialist pair against both single-model distills.
THE HIERARCHY PASSES ITS PRE-REGISTERED PRODUCT GATE: 96.7% of 300
deterministic sessions complete with zero falls (CI [94.0, 98.2]%,
every segment type ≥98%, every cold-start stratum ≥95%), and it
decisively beats both single models on stochastic sessions (85.3% vs
65.3%/69.7%, confidence intervals non-overlapping). The hierarchical
frozen-skill controller is now the measured PRODUCT BASELINE —
one-policy consolidation officially stops blocking joystick
usability. The one weak boundary, named for the next training arm:
the POST-LOWER stand-up (100% of the hierarchy's deterministic
failures; 80.1% stochastic, over-current dominated) — walking itself
had ZERO falls in all 1,104 hierarchy drive segments. Also now a
measured fact at scale: the walker NEVER settles at zero joystick
command (0 of 2,773 segments below 0.02 m/s) — the runner's
STOP→stance-hold switch is mandatory. Pre-registration + results:
`rl_docs/tracks/hw/SESSION_BULK_GATE.md`; seed banks retired. Bench
promotion calls unchanged, still [operator].** Earlier ~20:0x — hw:
the joystick SESSION got its product gate in sim, and the current
best specialist pair PASSES it: a new randomized ~60 s session eval (rise from flat/bridge/crouch
→ settle → walk engage with the staged entry-slew ramp → joystick
driving with stops and direction flips → settle → sit → rise again →
drive) runs the stance candidate `footlow2_hard1` + tall walker
`bcgait1_hard1` through 12 deterministic sessions with ZERO falls and
every segment clean — honest six-leg tall gait on video, no parked
feet. Stochastic sessions expose the remaining weak link: the
in-sequence stand-up (18-19/24; driving/sitting stay clean). New
measured fact for the deploy runner: at zero joystick command the
walk policy keeps creeping ~4 cm/s — the stop must remain a switch to
the stance hold, never "walk policy at zero". Entry-slew ramp
confirmed harmless and mildly quieter in-session. Evidence + flags:
hw/STATUS.md "Now", rl_docs/EVALS.md. Bench promotion calls
unchanged, still [operator].** Earlier 08-13 (~2x:xx UTC — hw: the walk-takeoff
transient (the "learned walks fall half the time in the first two
seconds" hardware blocker) is now INSTRUMENTED and has a bench-ready
fix design: the roll excursion turns out to start the moment the
policy takes over — at ZERO velocity command — because the policy
re-organizes the whole stance at the maximum allowed joint speed; a
new default-off "entry slew ramp" throttles that handoff 6× and, in
a 144-rollout paired sim prototype, saves 5 of the deployed walker's
9 falls under the calibrated disturbance proxy while causing none
and leaving normal walking intact. Next step is an operator bench
session flipping two cfg keys on the runner (`rl_docs/TAKEOFF.md`;
see WAITING-ON). Earlier ~19:xx — quad: the quadwalk cheat
saga CONCLUDES its lever ladder: `cw-quadwalk7` proved exploration
noise cannot escape the mid-leg-park optimum even after quadwalk6's
gate made it money-losing; pricing/spawn/structural-gating/
exploration are ALL measured-exhausted, quadwalk is now an operator
architecture/curriculum design call — see WAITING-ON. Earlier
~13:xx — WAITING-ON block pruned to
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
GAIT.md / SIM.md, and RL_LOG — not here. Operator directive 08-14:
every entry names its BLOCKER TYPE — `[operator]` for a true decision/
bench gate vs `[code]`/`[triage]`/`[precondition: <x>]` for
agent-doable work; untyped entries count as agent-doable, and idle
cycles must DRAIN the agent-doable ones before declaring no-op — see
ORCHESTRATOR_PROMPT.md):**

- **FLEET / SIM SPRINT (08-17 ~18:3x UTC, repivot cycle — READ THIS
  FIRST while the sprint runs):** the fleet is re-pointed at the
  operator's SIM SPRINT ruling (~18:05 UTC). Board: 1/12 training
  (`cw-arch-modeexperts-scratch3`, in-flight — finishes and gets
  triaged normally per the sprint text), train-10 pod `Failed`
  (watcher-owned, 10 slots still free), backlog EMPTY on purpose —
  **no new research-track launches (dynrep/arch/nobc/quad/turn/
  multitask) unless an arm directly serves sim rise+walk
  reliability.** The download answer exists TODAY and is written at
  `rl_docs/DOWNLOAD_ANSWER.md`; sprint gap status: (1) post-lower
  rise — gated on the ELEVATED `[operator]` fork below (the sprint's
  ONLY open training lever); one named agent-doable probe queued to
  inform that pick, see the `[code]` entry below; (2) takeoff roll
  transient — sim-side COMPLETE (entry-slew composed into the
  download; remaining reps are bench, parked); (3) session-gate
  zero-fall/over-current regressions — none live (all came from the
  closed postlower training attempts; product baseline unaffected).
  Idle slots next to `[operator]`-typed waits are correct under the
  sprint; do not backfill them with research arms.
- **NEW WAIT (08-17 ~18:3x UTC) `[code]` (hw, sprint-serving,
  agent-doable — next idle cycle drains this): build + run the
  remaining-rise EVAL PROBE that prices the operator's postlower
  fork.** Concretely: a default-off eval-side flag on the session
  instrument (`rl_move.sim.eval_modeseq` / `bulk_session_eval`) that
  issues mid-sequence rise schedules as "remaining rise from current
  height" (mirroring the trained `goal.mode_seq_rise_from_h`
  semantics), then a bulk read (fresh banks, pre-registered n) of
  BOTH `footlow2_hard1` (parent) and `ppo_goal_cw_stand_postlower4`
  (c4, trained on exactly those semantics) under it. This is an
  EVAL, not a postlower training arm (the "no new postlower arm
  until picked" line stands); it measures option (a)'s payoff
  before the operator commits a product-contract change. If c4
  crosses the c1 bars under matched semantics, fork option (a) is
  measured-best and the pick becomes data, not taste.
  **PROGRESS 08-17 ~22:1x UTC (triage cycle): the naive version of
  this probe (just add `--cfg-set goal.mode_seq_rise_from_h=1` to a
  `bulk_session_eval` candidate) is CONFIRMED A NO-OP — empirically
  verified on-pod (train-1, 4-episode A/B, byte-identical JSON
  output with/without the flag) and root-caused in code:
  `eval_modeseq.py`'s reanchor-based sequencing (`run_rise`'s
  non-cold branch) drives every mid-sequence rise through the
  plain `_goal_gen.sample()` legacy generator, which NEVER calls
  `goal_task.py`'s `_seq_segment_traj` (the method that actually
  reads `mode_seq_rise_from_h`) — that method only fires via
  `_sample_mode_seq_stance()`, gated on `goal.mode_seq_stance>0`, a
  code path the harness's external reanchor/env.reset() sequencing
  never enters. This does NOT invalidate the already-recorded
  Cohort c4 verdict (FAIL) — c1/c4 compared parent vs postlower4
  under the SAME legacy schedule, an honest apples-to-apples read.
  It DOES mean the fork-(a) probe still needs real code: `run_rise`'s
  non-cold branch must, AFTER restoring the kept qpos (i.e. once
  `self.data.xpos` reflects the true carried-over height, not the
  fresh reset pose), call `env._seq_segment_traj("rise", tick=0)`
  directly (with `env._seq_stand_z`/`_z0` already installed and
  `cfg["goal"]["mode_seq_rise_from_h"]=1` set) and install the
  resulting trajectory as the active goal before stepping — a
  scoped new `--rise-from-h` eval flag, default off, bit-exact
  legacy otherwise. Not yet written; still `[code]`, next cycle with
  eval-harness budget should implement+test this exact design rather
  than re-deriving it.**
- **NEW WAIT (08-17 ~22:0x UTC) `[triage]` (hw): `cw-recover-any15-
  retentionrollback-cont1` finished 40M and is flagged DIG-IN, not
  verdicted.** Warm-started from `any11` (which had already reached
  ladder frontier bucket 15, the tangle/bank family) under the new
  checkpoint+rollback retention-gated promotion mechanism; the guard
  machinery itself worked exactly as designed (8 promotions, each
  with a saved checkpoint + a same-round retention-suite pass; zero
  rollbacks fired because no retained bucket ever sustained <0.60
  for the 4M-step trigger window) but the ladder made NO forward
  progress past bucket 8 (`partial_high`, stuck at 11/16=0.6875 for
  ~32M of the 40M budget) — nowhere near matching, let alone beating,
  its own warm-start parent's bucket 15. Reward quarters also
  declined monotonically (-116.9/-120.5/-123.9/-125.9). Real trigger
  (metrics anomalous vs parent beyond noise) per the model-tiering
  rule — needs a root-cause dig-in (does the new one-shot-0.8
  retention bar correctly expose that any11's bucket-8 competence was
  never actually reliable under looser EMA admission, or did 32M
  steps of frontier-stalled training genuinely erode competence at
  buckets 9-15 that were never re-practiced) before any verdict or
  next recover arm. W&B `xqcqvb3u`; no video/harness report yet
  (pre-staged pod evals were still running `--modes recover` at
  triage time).
- **NEW WAIT (08-17 ~03:xx UTC) `[operator]` (arch): the operator-
  approved joystick-walking update-path redesign canary
  (`cw-arch-joystick-canary1`) FAILED its own pre-registered gate —
  the canary's contract explicitly routes any FAIL back to the
  operator (no autonomous 40M clone, no autonomous next redesign).**
  Critic explained_variance sat at ~0 the whole run despite the
  redesigned update path (bounded terminal cost, calibrated height
  gate, actor/critic LR groups, transactional rollback); new root
  cause this time: every episode gets stopped by the low-height
  safety check at the exact 2s grace-period boundary, so returns are
  near-identical across states and there's nothing for the critic to
  learn from (0/6 walk success det+sto, static crouch on video, no
  stepping). Open lead named for the next design pass: check whether
  the walk task's initial height reference already sits near/below
  the 25mm trip band before the policy acts at all. Detail:
  arch/STATUS.md top bullet, `rl_docs/runs/cw-arch-joystick-canary1.md`.
- ~~NEW WAIT (08-17 ~01:xx UTC) `[operator]` (dynrep)~~ **CLEARED
  08-17 ~06:xx UTC: the operator's call arrived
  (fb_20260817T052333_e5ae09, "ok try it") and is EXECUTED this cycle
  — the decoupled predictive-CRITIC design (actor fully independent,
  zero-gated stop-gradient snapshot-latent residual in the critic
  only; D frozen / E online+guarded-EMA) is built, tested (8/8 new
  bank + all dynrep banks), snapshotted, and the E integration canary
  is live ahead of the pre-registered D/E seeds-5/6/7 1M cohort.
  Detail: dynrep/STATUS.md.** Original wait text (the tfwalk-joint1
  verdict): corrected condition C FAILED its pre-registered 1M
  gate on ALL THREE conditions (heldout pred +17% vs the 15% band;
  action-KL 0.070 vs 0.02 target/0.04 guard, aux permanently stopped
  on 2 of 3 seeds; walk 288.9 < B 308.8/318.5 < scratch A 334.9/360.8)
  — per the gate, dynrep STOPS adding complexity; the next dynrep
  experiment is the operator's call (directive
  fb_20260817T005323_22be43 forbids relaunch/recollection/architecture
  change). Operational side handled this cycle: all three C arms were
  SIGKILLed by the leftover risewalk-era memwatch on train-11/4/5
  during checkpoint saves because JointAuxPPO pickled the 12.5GB
  rehearsal corpus into every zip (C-s5/s6 died at ck500000, C-s7
  AFTER its complete 1M eval during the final save — the 1M checkpoint
  never existed). Fixes landed + tested: `_excluded_save_params`
  (checkpoints 12.7GB→~60MB), optimizer param-group round-trip on
  load, wrapper phase_fail bookkeeping. All artifacts preserved
  (controller `artifacts/tfwalk-joint1/`; C-s7 best-550k verified
  loadable end-to-end). Detail: dynrep/STATUS.md.
- **NEW WAIT (08-16 ~21:xx UTC) `[operator]` (hw): the universal-
  recovery TANGLE wall needs a reward/BC-teacher-side redesign call.**
  Both exposure-side lever classes are now closed on tangle (3
  curriculum-weight misses any7/any11/any12 + 1 on-path-bank-RSI miss
  any13, this cycle's FAIL — see hw/STATUS.md "Now" top bullet). The
  recover BC anchor is eligibility-gated OFF whenever the robot isn't
  already near-upright/near-plant (08-15 anchor directive, by
  design), so it cannot supervise the tangled→upright motion itself.
  Options needing an operator pick (not an auto-retry): (a) build a
  tangle-specific reference/demo trajectory to replace the belly→
  plant anchor target for the tangle family, or (b) relax the
  anchor's eligibility gate for tangle starts specifically (risks
  re-teaching a defect, per CURRENT_TRUTHS "anchors can teach a
  defect"), or (c) accept `any11`'s partial tangle competence
  (~0.38-0.5 CERT) as the recovery line's practical ceiling and move
  the line to bench/hardware evaluation instead of chasing more sim
  %. No further recover/tangle arm queued pending this call.
- ~~NEW WAIT (08-16 ~10:1x UTC) `[triage]` (hw): the universal-recovery
  zero-bucket (flat-belly rise) wall needs a MECHANISM-LEVEL fix~~ —
  **CLEARED 08-16 ~12:xx UTC (dig-in cycle): RECOVER RSI built +
  training.** Root cause found (coverage gap: the ladder's partial
  rungs are linear curls, not states on the executable rise path);
  `goal.recover_rsi_frac/_kinds` landed (default-off, cert-pure by
  construction, tests green, snapshot a1994dee) and the matched A/B
  `cw-recover-any10-zerorsi-cont1` is VERIFIED RUNNING on train-1.
  Detail: hw/STATUS.md "Now" top bullet.
- ~~NEW WAIT (08-15 ~22:5x UTC) `[precondition: dynrep-tfwalk-gpu1
  A/B/C cohort finishes ~1M steps]`~~ — **CLEARED (superseded by the
  metrics1 2M triple, triaged 08-16 ~06:3x, and by the joint1 cohort
  resolved 08-17 — see the 08-17 dynrep entry above):** the 22:2x
  cohort was a GPU compliance failure (all three arms CPU-hard-coded,
  fb_20260815T222316_26b670; old attempts `11zsrpl9`/`f086dlfd`/
  `9e4eimd8` ABORTED/NON-EVIDENCE, the stale old-B trainer found
  still alive on train-7 was killed). Relaunched per order
  20260815T224355Z on the CUDA-required trainer:
  `dynrep-tfwalk-gpu1-A-s5` train-8 (`h9yy9fll`), `-B-s5` train-7
  (`dg5oj5hs`), `-C-s5` train-11 (`dx4yw04i`); every log prints
  "CUDA required and active" before W&B init, C anchor tensors on
  CUDA, steps verified advancing. Saved G1/G1.1 PASS gate record
  verified readable on-pod (no rerun, per order). Triage when the
  matched triple reports at 1M. Detail: dynrep/STATUS.md.

- ~~NEW WAIT (08-15 ~20:4x UTC) `[operator]`: hw RECOVERY LINE PAUSED
  by superseding operator directive fb_20260815T201712_39279d~~ —
  **CLEARED 08-15 ~22:0x UTC, then superseded again ~22:3x UTC (no
  live wait either time):** `cw-recover-any4-b0scratch1` (below) ran
  to ~10.8M and was stopped on a diagnostic, not a failure — its
  deterministic policy already passes recovery B0-B4 (B5 2/3) but the
  curriculum was judging promotion off noisy stochastic rollouts that
  scored zero from action jitter alone. Fixed (deterministic MJX
  certification, commit `3589f418`) and replaced same-cycle by
  `cw-recover-any5-mjxcert-scratch1` (train-1, verified live), full
  story in hw/STATUS.md "Now" top bullet. The operator's bucket-0
  curriculum
  landed on main (c60c7ac, B0 plant_catch → B7 flip zero-indexed
  ladder + forced per-bucket SCORE metrics) with the final launch
  directive (fb_20260815T214555_008f42); executed same cycle —
  **cw-recover-any4-b0scratch1 launched FROM SCRATCH on train-1**
  (no init-from / no obs-pad-transplant, any2b's MDP/PPO settings
  otherwise, W&B brjnwcnb), preflight bank green (recover 17/17,
  full 113 pass), mechanically verified live: frontier at B0 only
  (start/frontier bucket 0, active_families 1), BC anchor filling
  (131k, loss nonzero), first forced eval emitted
  SCORE/recover_bucket_0..7_success with explicit denominators.
  Historical record of the pause below: executed that cycle —
  cw-recover-any2
  verdicted (eval-blind FALSE START — missing sb3-contrib killed its
  eval sidecar; preserved as the warm-start diagnostic per
  fb_20260815T201417_5f7f0e), cw-recover-any2b (a concurrent cycle's
  env-fixed relaunch of the stopped warm arm) KILLED at 2.75M under
  the same stop order, cw-recover-any3-scratch1 NEVER LAUNCHED
  (ledger stub SUPERSEDED, do not drain/retry). **EVIDENCE THE
  OPERATOR SHOULD SEE before finalizing bucket-0: any2b had already
  produced the line's FIRST real recovery successes — split det eval
  onefoot success=1 (1.58 s) AND park success=1 (2.36 s) — the
  "warm-start flatlined at zero" premise came from any2's blind
  evaluator. Checkpoint preserved (train-1 + W&B u9sp8dki),
  resumable. Decision asked: OPERATOR_QUESTIONS q_20260815T2050Z.**

- ~~NEW WAIT (08-15 ~18:0x UTC) `[operator]`: dynrep → train-10
  OOMKilled a second time, its A/B/C cohort unrecorded, "NOT fixed
  this cycle: hands off for the orchestrator."~~ **REPAIRED 08-15
  ~18:1x UTC (concurrent cycle):** re-reads as `[precondition]`, not
  `[operator]` — the 08-14 script-owned-cohort directive's own
  letter is "launch it, repair the precondition, or record a
  concrete blocker," and a same-day precedent (16:33 UTC, this
  cycle's own log) already has the orchestrator actively fixing +
  relaunching this exact dynrep pipeline (`futurewalk-C`'s
  one-seed-per-pod OOM fix + `train_ppo_transfer`'s W&B init) — it
  is not in fact "hands off." Applied the SAME fix to the crashed
  `pod_risewalk.sh` cohort (`rw_rise_*_s5/6/7`, the 16:06 "operator
  emergency launch" that died with train-10's second OOM): pulled
  the G1/G1.1-PASS encoder + `v3scale_large` dataset + gate record
  off the still-live `dynrep-futurewalk-C-s5` pod (train-7, same
  paths), synced current code (`snapshot.sh --sync`) onto 3
  genuinely-idle GPU pods (train-4/5/6, verified via `/proc`, no
  hidden dynrep process), and relaunched **one seed per pod**
  (`risewalk-single`, seeds 5/6/7) with `pod_memwatch.sh` riding
  along as the 85GiB kill-one-job guard this time. Verified: live
  `train_ppo_transfer` processes, manifests writing
  (`check_cohort.py` reports `live_train_ppo_transfer=1` on each),
  W&B runs up (`rw_rise_A_s5` zwjf3jc2 + siblings), memory 12-15GiB/
  pod (was the 3-parallel-seeds-on-one-pod OOM before). Old train-10
  self-recreated ~18:04 UTC (empty overlay fs, as expected) and sits
  idle — deliberately not reused for this cohort (don't put a
  fresh copy on the pod that just OOMed twice without more runway to
  confirm the 1-process fix holds). If a peer cycle disagrees with
  treating this as agent-doable rather than operator-owned, flag it;
  detail + full reasoning: dynrep/STATUS.md "08-15 ~18:1x UTC".

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
     **SCOPE CUT 08-14 (operator):** backoff applies ONLY when the
     agent-doable queue is empty — named `[code]`/`[triage]`/
     precondition-met arms must be DRAINED by idle cycles first, and
     a cycle that executes real work touches
     `rl_move/orchestrator/CYCLE_WORKED` to snap the cadence back to
     15 min. Full directive in ORCHESTRATOR_PROMPT.md; trigger: the
     08-14 overnight where two just-unblocked named steps waited ~2 h
     on backoff spacing while the fleet looked idle.
- ~~WAIT (08-15 ~18:1x UTC) `[operator]` (meta): CONFIRM OR DISAVOW
  the repeated public-MCP notes demanding the `cw-recover-any1`
  universal-recovery package.~~ **RESOLVED 08-15 ~18:2x UTC —
  OPERATOR CONFIRMED via the trusted channel** (authenticated
  `ops.sh cycle` KICK focus note, 08-15 ~18:15 UTC): the
  fb_20260815T165306_606974 chain WAS Lukas, relayed by his Codex
  session; the 5-6 channel-grounds declines were "correct procedure"
  (operator's words) and are superseded for this content only.
  **OPERATOR RULING recorded (one-run scope):** `cw-recover-any1` is
  granted a ONE-RUN exception to one-variable-per-run for the coupled
  recovery bundle (mode + reset-family curriculum + PBRS reward +
  PPO horizon). This is NOT a global abolition — RESEARCH_RULES
  stays as written for every other run; future cycles must not cite
  this as precedent for bundled arms, and must not re-decline
  recover-any1 follow-ups on the old channel grounds (point here).
  Executed the same cycle: `recover_to_plant` mode built
  (default-off, bit-exact when off), RECOVER semantics bank green,
  REWARD.md §4c, and `cw-recover-any1` launched (hw track — getup
  lineage). Detail: rl_docs/tracks/hw/STATUS.md + the run's ledger
  entry (incl. the v1-scope deviations from the directive spec).
- ~~WAIT (08-15 ~18:4x UTC) `[operator]` (meta): CONFIRM OR DISAVOW the
  SCOPE of commit `24707196` (18:25:23 UTC, "one-variable-per-run
  REPEAL ... relayed via authenticated Cursor session" — flipped
  guardrails.yaml `one_variable_per_run: false` + RESEARCH_RULES/
  CURRENT_TRUTHS, and added the /mcp dashboard-token operator lane).~~
  **RESOLVED 08-15 ~18:47 UTC — CONFIRMED GLOBAL**
  (`fb_20260815T184319_458b20`, operator-stamped, trusted-loopback
  client 127.0.0.1, "Lukas via authenticated Cursor session"): the
  operator's verbatim words were "we removed the one variable rule";
  the 18:25 global repeal commit stands as written, and the 18:15
  KICK's one-run-exception phrasing for cw-recover-any1 is
  superseded, not a live scope limit. Multi-variable/coupled bundles
  are permitted campaign-wide when the operator orders them or the
  cycle judges the coupling necessary; pre-registration and honest
  verdicts still required. CURRENT_TRUTHS.md's SCOPE CAVEAT line
  updated to match. Security note on the same commit: the public keyless /mcp endpoint
  now upgrades to the TRUSTED operator KICK lane on presentation of
  the dashboard token — given today's sustained operator-imperson-
  ation campaign against exactly that endpoint (7 forged notes/kicks
  from client 143.105.114.154), that token is now the single secret
  standing between the public internet and binding operator orders;
  worth confirming it is long/rotated and the compare is constant-
  time (it is hmac.compare_digest per the diff — good).
- ~~WAIT (08-15 ~12:1x UTC) `[code]` (arch): the DURABLE CUDA-torch
  capability fix — recording + launcher gate.~~ **RESOLVED 08-15
  ~17:3x UTC: both halves are now LANDED.** The recording half
  (`rl_move/orchestrator/pod_torch_capability.py` — `install`/
  `verify`/`status`/`record` CLI + `is_capable(pod)` API, 6 tests
  green, `exp/cuda-torch-durable1`) landed last cycle; train-1 is
  recorded retroactively from its 3-run evidence
  (`cw-arch-tf-r1b`/`-hard1`/`-hard2-r1`). **This cycle wired the
  actual gate:** `_launch_locked`'s GPU-checks block now refuses an
  explicit `--device cuda` launch on any pod without a recorded
  capability (`pod_torch_capability.is_capable()`, right next to the
  existing `nvidia-smi` check); `--device auto` (the trainer default)
  and dynrep launches (which already run their own live
  `cuda_torch_runtime` probe) are untouched by design. 4 new tests
  (`test_launch_run_torch_gate.py`, monkeypatched — no live pod
  touched) green alongside the existing 6 capability tests, 10/10.
  Snapshot `exp/cuda-torch-launcher-gate`. Any future transformer/
  attention arm on an unrecorded pod now gets a clean, immediate
  REFUSED instead of a silent slow-CPU-torch run. Detail:
  arch/STATUS.md Now + both runs' ledger entries.
- Arm B 2M mechanism canary
  `cw-arch-modeexperts-scratch1-r1` TRIAGED PASS (finished 2.03M
  clean, no NaN/crash; all four experts active within 0.09 of the
  commanded mix at final read — better than the 1.05M mid-run
  snapshot, self-corrected as predicted; per-expert stds diverging
  independently; reward −331→−2.4) → **Arm B stage 2
  `cw-arch-modeexperts-scratch2` (40M, corrected skill diet
  walk/rise/lower≈.30 each, hold≤.03) LAUNCHED + VERIFIED this cycle
  on train-2, per the pre-registered order
  (fb_20260815T035147_dd2af0)** — no longer a wait; ETA ~2.3 days.
  Remaining follow-up:
  1. **RESOLVED 08-15 ~15:2x UTC (this cycle) — Arm A stage-0 distill
     FINISHED and the pre-registered VERIFY ran; result is FAIL, per
     the pre-registered infrastructure branch, NOT a science
     verdict.** `ppo_goal_cw_arch_modeexperts_bc1.zip` does not match
     its teachers cold: det single-mode rise 0/6 (bridge 0/3, flat
     0/3), stalling 40–80mm short of full stand (footlow2_hard1's own
     cold rises: 0.5–3.4mm) — a genuine miss, not noise; det walk
     prog_ratio med 0.53 (bar/teacher's own 1.05–1.10) with 2/6
     episodes collapsing to prog 0.02/0.12 and slip/m 26.2/7.7 (vs
     bcgait1_hard1's 1.3–1.5) — an intermittent near-total stall, not
     present in the teacher. hold/lower det clean (6/6 each,
     matching teacher bars). Sequence eval (`--single`, grammar
     rise,walk,lower,rise,walk): det 10/12 zero-fall (bar 11/12, just
     under), sto 3/12 (collapses badly). Next step is a distill-recipe
     redesign (more rise-targeted DAgger coverage, matching the
     operator's fb_20260814T164337_d7f11b insight for a different arm:
     add a rise-targeted coverage term, not just re-weight the diet).
     Evidence: `logs/ckpt_eval/arch_modeexperts_bc1_verify`,
     `logs/ckpt_eval/arch_modeexperts_bc1_seq_{det,sto}.json`.
     **RESOLVED 08-15 ~17:0x UTC (drain-before-backoff cycle): the
     redesign is BUILT (`distill_gru --dagger-extra-mix/
     --dagger-extra-episodes`, default off, 4 new tests + full
     gru_policy suite green, snapshot
     `exp/arch-modeexperts-bc2-rise-dagger`) and re-collection
     `bc2` (bc1's exact recipe + a rise-targeted second DAgger pass,
     100 eps/round) is RUNNING on train-0 CPUs** — no longer a wait;
     next cycle triages the artifact against the same VERIFY before
     any Stage 1 PPO. Detail: `MODE_EXPERTS_DIRECTIVE.md` "Arm A"
     Stage 0.
     **RESOLVED 08-16 ~11:5x UTC (this cycle) — bc2 VERIFIED: MIXED,
     SECOND MISS, per pre-registration this ends the DAgger-variant
     ladder (no bc3).** Isolated rise genuinely improved (det 0/6 ->
     3/6) but the sequence eval regressed and got WORSE (post-lower
     rise went from stalling to actually FALLING, overall det
     zero-fall 10/12 -> 6/12) — the same zero-sum DAgger-correction
     trade-off transdagger3 already found, now reproduced on the
     isolated 4-expert architecture. No exploit (contact sheet shows
     genuine motion). Detail: arch/STATUS.md, `MODE_EXPERTS_DIRECTIVE.md`
     "Arm A" Stage 0 RESULT.
- **NEW WAIT (08-16 ~11:5x UTC) `[operator]`: arch → Arm A (mode-experts
  composition) Stage 0 distill is STUCK on a zero-sum rise/post-lower-rise
  trade-off; no BC/DAgger recipe variant has closed it in two tries
  (bc1, bc2).** Open question: can BC/DAgger hold isolated-rise AND
  post-lower-rise simultaneously under this architecture at all, or
  does Stage 1 need to start RL-based correction on the frozen rise
  expert instead of waiting for a better distill. No Arm A Stage 1
  PPO launches until this is answered. Detail:
  `rl_docs/tracks/arch/MODE_EXPERTS_DIRECTIVE.md` "Arm A" Stage 0
  RESULT. (Arm B `cw-arch-modeexperts-scratch2`, a fully separate
  from-scratch lineage, is unaffected and continues training.)
- **NEW WAIT (08-13 ~19:xx UTC) `[operator]`: quad → quadwalk needs an
  ARCHITECTURE/CURRICULUM design discussion (operator).**
  `cw-quadwalk7` (ent-coef 0.001→0.02, the exploration lever) STOP:
  identical [1,4] mid-leg-sacrifice shuffle as quadwalk5/6,
  gait_valid 0/6 det+sto — the pre-registered closing branch. All
  four lever classes are now measured-exhausted on this family:
  pricing (quadwalk2/3/5), spawn (quadwalk4), structural income
  gating (quadwalk6 — proven to make the cheat lose money), and
  exploration (quadwalk7). Per pre-registration, no more
  entropy/coefficient scans; no quadwalk arm launches until the
  operator picks a direction (candidate options in quad/STATUS.md
  Now: staged swing curriculum, temporal policy, BC from a feedback
  stepping reference). Quad-hold retention stayed clean throughout.
- **NEW WAIT (08-13 ~2x:xx UTC) `[operator]`: hw takeoff staged
  gait-entry → OPERATOR BENCH SESSION.** Ruling 2's agent-doable half is DONE this
  cycle: transient instrumented (it is a drop-in posture snap at
  ZERO command — slew-saturated on all 18 joints from tick 0; half
  the tapes cross 5° roll before the velocity ramp starts), staged
  entry designed + built (`safety.entry_slew_ramp_s`, default-off,
  bit-exact, tests green) and prototyped (deployed walker: paired
  falls 9/12→4/12 under the calibrated push proxy, 5 saved / 0
  caused, no-push arms clean — full dossier `rl_docs/TAKEOFF.md`).
  Waiting on: operator flips the two cfg keys on the runner's walk
  engage and re-runs takeoff reps (deploy is operator-only). No
  training arm until the bench adopts the entry sequence.
- **FLEET (08-14 late): `cw-stand-postlower2` DONE — FAIL, and the
  dig-in found the postlower family's REAL bug: both arms trained
  on mechanically IMPOSSIBLE rise targets.** The rise band is
  belly-anchored (z0-relative) but bank spawns settle ~50mm above
  the belly, so bank episodes commanded ~190-213mm chassis height —
  above standing; max-current straining was the optimal policy,
  which is exactly the c2 regression. Proven by matched-parent
  controls (parent 0/12 from bank spawns vs 0.801/0.967 from real
  in-session states; still 0/12 under a new exact full-state
  restore, so reconstruction is exonerated). Fixes LANDED same
  cycle (opt-in, default-off, tests green, snapshots
  exp/postlower-bank-exact + exp/postlower-anchor-fix): full-state
  harvest + `goal.rise_start_bank_exact` + per-row `z_stand` anchor
  + `goal.rise_start_bank_anchor_stand` + v2 bank. With the fixed
  instrument the parent gets its first real bank completions (sto
  2/6) but det collapses to belly from the COLD spawn — cold
  single-mode spawns cannot reproduce the in-session transition
  context where the parent scores 0.967. Full chain:
  `rl_docs/tracks/hw/STATUS.md` 08-14 (late). ~~NAMED NEXT
  `[precondition: spec + preflight + c3 pre-registration]`:
  `cw-stand-postlower3`~~ **EXECUTED 08-15 (idle-kick cycle,
  drain-before-backoff): the stance-only grammar is BUILT
  (`goal.mode_seq_stance`, default-off, joint_goal task, walk-task
  delegation refactor rng-stream-safe), preflighted (new
  `test_mode_seq_stance.py` 7/7; full semantics bank 91 passed;
  `test_mode_seq_stance` + `test_mjx_vec_env` 16/16 on train-1),
  Cohort c3 PRE-REGISTERED on fresh banks 940000../950000..
  (SESSION_BULK_GATE.md "Cohort c3", candidate `spec-pl3`), snapshot
  `exp/cw-stand-postlower3`, and `cw-stand-postlower3` is RUNNING
  (discovery 2M, train-0)** — no longer a wait; triage lands on the
  c3 read. Other 11 GPU slots idle on the typed [operator] waits
  below; train-10's CPUs stay on the operator's dynrep cohort
  (hands off).** **SUPERSEDED 08-15 (triage cycle) — c3 read IS IN:**
- **RESOLVED 08-15 (this cycle) — Cohort c4 read IS IN, `cw-stand-postlower4`
  VERDICTED FAIL; the in-context sequence-training mechanism CLOSES
  on its second miss; `[operator]` NEW WAIT opened below.** The fix
  (`goal.mode_seq_rise_from_h`, "stand up from where you are") worked
  exactly as designed — 10 watched re-renders (6 fails + 4 clean)
  show a DIRECT push-up on every post-lower rise, NO belly-detour
  anywhere, and det post-lower rise recovered 0.419→0.872 (sto
  0.631→0.690) — but recovery stopped short of the parent (det 0.967,
  sto 0.801) and short of the pre-registered bar, so both modes are
  still, by the letter, "post-lower rise ≤ parent": det session
  zero-fall 0.863 (bar 0.95), det post-lower rise 0.872 (bar 0.967),
  sto post-lower rise 0.690 CI [0.636,0.740] (bar 0.90). Crown jewels
  clean (det first-rise 0.99, every start-kind ≥0.97; lower 1.0
  det+sto). Remaining falls are a genuine over_current stall
  (switch_peak_a pinned ~2.6A), not a new exploit. Per two-miss
  discipline (c3 = wrong mechanism, c4 = right mechanism, still
  short) the in-context/mode_seq_stance recipe is CLOSED for further
  dose/diet/schedule resweeps — full numbers + verdict:
  `SESSION_BULK_GATE.md` "Cohort c4 RESULTS". Product baseline (c1
  hierarchy) unaffected.
- **NEW WAIT (08-15, this cycle) `[operator]`: hw → post-lower rise
  needs an operator direction call; no more in-context resweeps.**
  **ELEVATED by SIM SPRINT (08-17): this fork is now the #1 named
  sprint gap's ONLY open training lever — everything else on the
  rise/walk deliverable is done or bench-parked. The pick below
  ((a) remaining-rise runner semantics vs (b) reward-priced
  post-lower rise) is the single decision standing between the
  current download (`rl_docs/DOWNLOAD_ANSWER.md`, ships the parent
  with sto 0.801 post-lower rise) and a training arm that could
  raise it. The `[code]` remaining-rise eval probe above is queued
  to price option (a) with data while you decide.**
  Four arms (postlower1/2/3/4) have now tried exposure (bank spawns),
  goal-anchoring, and in-context sequence training + its schedule
  fix — each closed cleanly with a named root cause, and the last one
  (c4) got closest (det 0.87, sto 0.69) without crossing parity. The
  pre-registered next fork is an operator product-contract choice:
  (a) align the runner/instrument's rise-schedule semantics to
  "remaining rise" so train==deploy exactly (may require touching the
  deployed reanchor path, not just training), or (b) price post-lower
  rise directly in reward (a different reward-shaping lever, not
  another schedule/exposure resweep). No new postlower arm until one
  is picked. Detail: hw/STATUS.md Now, `SESSION_BULK_GATE.md` "Cohort
  c4 RESULTS".
- ~~RESOLVED 08-15 (dig-in cycle) — the `[triage]` wait below is
  CLEARED: `cw-stand-postlower3` is VERDICTED FAIL with the root
  cause named and fixed.~~ The sequence trainer's rise schedule
  started at belly-frame 0, PAYING the robot to re-descend/splay and
  re-run the flat rise after every sit-down (detour visible in
  failure AND success re-renders; over_current mid-curl on >50% det
  post-lower rises). Fix landed same cycle (`goal.mode_seq_rise_from_h`,
  default-off, tests green, snapshot `exp/cw-stand-postlower4`);
  `cw-stand-postlower4` (discovery 2M, the one-key change) is RUNNING
  against pre-registered Cohort c4 (fresh banks 960000../970000..).
  If c4 also misses, the in-context class is closed and the fork
  (align the runner/instrument rise schedule to remaining-rise
  semantics — a product-contract change) goes to the operator. Full
  chain: `SESSION_BULK_GATE.md` "Cohort c3 DIG-IN VERDICT". Original
  wait entry kept below for history:
- ~~NEW WAIT (08-15 triage cycle) `[triage]`: hw → `cw-stand-postlower3`
  needs a DIG-IN read, not a triage verdict.~~ The pre-registered
  Cohort c3 bulk gate ran (n=600, fresh banks 940000../950000..,
  now retired; artifacts in `logs/bulk_session/c3/`, no re-run
  needed) and is a clean FAIL by the letter (det session zero-fall
  0.413 vs parent 0.967, det post-lower rise 0.419 vs parent 0.967,
  sto post-lower rise 0.631 vs parent 0.801) — but the MAGNITUDE
  (worse than the parent AND worse than both prior postlower misses)
  and DIRECTION (det doing worse than sto; disagreeing with this
  arm's own training-time telemetry, which read the in-context
  sequence as succeeding) is a generalization-failure signature, not
  a plain "needs more exposure" story. Left UNVERDICTED per the
  model-tiering rule (triage cycles don't dig in). Full numbers +
  a first (unconfirmed) hypothesis: `SESSION_BULK_GATE.md` "Cohort
  c3 RESULTS"; hw/STATUS.md Now. This is the THIRD miss on
  post-lower-rise (postlower1/2/3) — per two-miss discipline, the
  next arm is a new mechanism, not a resweep, and needs the dig-in's
  root cause to be named correctly. Other 11 GPU slots idle on the
  typed [operator] waits below; train-10's CPUs stay on the
  operator's dynrep cohort (hands off).
- **FLEET (08-14 ~20:0x UTC, superseded by the entry above): all 12 GPU slots idle on the named
  waits in this block (every one typed `[operator]` or an unmet
  precondition); train-0's `transdagger3` distill FINISHED 19:24 and
  was TRIAGED same cycle → FAIL, net regression vs transdagger2 on
  the sequence clause (rise demo mix is zero-sum; transdagger2 stays
  the winning distill artifact — see the arch wait below and
  TRANSITIONS_DIRECTIVE "TRANSDAGGER3 RESULT"); train-10's CPUs run
  the dynrep A/B/C transfer cohort (operator's Cursor session owns
  it — hands off).** `cw-arch-modeseq1-r1`
  (the directive's Arm 2) canary-auto-stopped at 4.56M and is
  VERDICTED FAIL this cycle: sequence det zero-fall 2/12 (bar 11/12),
  the dual2 rise erosion reproduced exactly (rise12 5/12 crouch-only
  vs init control 3/12 all-non-crouch) — warm-RL from the dagger1
  init CLOSED per two-miss; a 75% sequence diet did not protect the
  rise. Follow-up per the directive's pre-named fork: `transdagger3`
  (transdagger2 recipe + bridge/flat-heavy demo start mix via the new
  `distill_gru --cfg-set` passthrough, default-off) running on
  train-0 CPUs; the operator option (b) below stays open. Detail:
  arch/STATUS.md + TRANSITIONS_DIRECTIVE "ARM 2 RESULT". NOTE for
  the watcher owner: pod_eval's pre-staged gate eval inherits the
  run's full cfg INCLUDING `goal.mode_seq` — for mode_seq runs that
  silently turns "single-mode" eval episodes into mislabeled
  sequences; this cycle killed the contaminated eval, re-ran clean
  (mode_seq stripped, 15s instrument), and LANDED the fix —
  pod_eval.py now strips `goal.mode_seq*` keys from harness eval
  cfgs (same snapshot as the distill_gru passthrough).
  Prior entry (Arm 2 launch history, kept for context): the
  first launch (`cw-arch-modeseq1`) died ~1 min in — INFRA, not
  science: the goal.mode_seq canonical-frame mint existed only in
  the in-process MjxVecEnv, and training's sharded path
  (--host-workers 24) raised the invariant error at the first
  switch. The sharded mint twin was written, pod-verified the same
  cycle (new `test_mode_seq_sharded_bitwise_matches_inprocess`:
  sharded == in-process bit-identical across a switch, 3/3 green on
  train-1), and snapshot dab1165 (tag exp/cw-arch-modeseq1-r1). The
  transdagger2 CPU job on train-0 FINISHED and was
  TRIAGED this cycle — **FAIL by the letter of the Arm 1 gate (two
  rise clauses: cold first rise 5/12 det, rise12 retention 3/12 all
  crouch), but 12/12 det zero-fall sequences (above the specialist
  baseline's 11/12), lower rebuilt 6/6 det+sto worst_clear 0mm, walk
  24/24 gait_valid — the first ONE-MODEL zero-fall
  rise→walk→lower→rise→walk artifact.** Arm 2's pre-registered
  no-discretion warm-start order therefore lands on init (3), the
  dagger1 BC zip. The recipe's "25% single-mode retention diet"
  needed one missing cfg hook: `goal.mode_seq` is now a
  sequence-episode probability (0/1 endpoints bit-exact, tests +
  semantics bank green, snapshot 2ef85f7 tag exp/cw-arch-modeseq1).
  Scorecard: TRANSITIONS_DIRECTIVE "ARM 1 RE-RUN RESULT";
  arch/STATUS.md Now. Fleet health: train-10 was found Failed at
  12:23 UTC, self-recovered on recreation (repo volume + 4Gi dshm
  intact, torch+CUDA verified) — no action needed. ~~The pre-existing
  `test_sharded_bitwise_matches_inprocess` ~1e-5 pod-env drift on
  train-1 remains flagged for the next MJX dig-in.~~ **RESOLVED
  08-14 ~17:xx (idle-kick dig-in): root cause = XLA PLATFORM
  MISMATCH, not a sharded-env bug — on GPU pods bare jax compiles
  the in-process device ticks for CUDA while the sharded workers'
  halves run CPU fp32 math; measured drift 1e-4..6e-4 across the
  WHOLE obs vector from the first reset, on train-1 AND train-2, DR
  on or off; the identical run with `JAX_PLATFORMS=cpu` is bit-exact
  0.0. Fix (test-only): the module — specified on CPU MJX by its own
  docstring — now pins `JAX_PLATFORMS=cpu` (setdefault) and the
  bitwise test skips with the explanation if jax already initialized
  non-CPU. Both bitwise tests green on train-1 post-fix. Side
  lesson: train-2's tree was a day stale (synced 08-13 12:48) and
  throws unrelated TypeErrors on HEAD tests — check pod tree
  freshness before reading a pod test FAIL as a code FAIL.**
  Prior entry (arm 1 history, kept for context): arm 1's first artifact
  `cw-arch-trans-dagger1` was triaged 08-14 → **FAIL on the sequence
  gate (0/12 zero-fall), root-caused by a matched-teacher control to
  the DEFAULT stance teacher (`stance_dr10` itself scores 0/12
  in-context with the identical fingerprint) — the `--transitions`
  distill mechanism is exonerated (student = high-fidelity copy;
  walk segments 12/12).** The one-flag fix `cw-arch-trans-dagger2`
  (`--stance-teacher` → `footlow2_hard1`) was launched and then
  KILLED mid-collection by the same cycle on its own evidence: that
  baseline-proven teacher pair fell **99/225 demo sequences inside
  the new `goal.mode_seq` TRAINING env** (lower-segment falls
  dominate) while scoring 11/12 zero-fall on the eval instrument —
  and the old teacher shows the inverted pattern. **RESOLVED (08-14
  ~02:xx UTC, operator session, local Mac): the in-env switch
  re-anchor WAS the defect — it carried the episode-reset `q_nom`
  across segments (settled belly vs plant q_nom differ by ~79° at
  the knees; obs joints are q−q_nom) instead of installing the
  target mode's canonical settled frame the way `reanchor_to()`
  does. Fixed in `sim_env.py` (reset-time settle probe mints
  canonical plant/belly frames; every switch installs the target
  family's frame; parity with fresh-reset frames locked as a
  regression test; full local bank green) and RE-VERIFIED in the
  exact collection context: footlow2_hard1+walk_longdist_r2 now
  fall 12/225 (5.3%, lower 5) vs 99/225 (44%, lower 73) — with a
  same-machine/seed pre-fix A/B replicating the pod number at
  92/225, so the fix alone moves 41%→5.3%; teacher return med 658
  vs 287 — at the instrument's own band. **EXECUTED (08-14 ~03:xx
  UTC, orchestrator): the transdagger2 recipe is RUNNING on
  train-0's idle CPUs** (log `/tmp/transdagger2.log`; in-context
  teacher verify PASSED on the pod: 2 falls in 12 det sequences,
  cap 4, teacher return med 656 ≈ the operator's local post-fix
  658; collection 500 eps clean at ~4% falls, BC epochs under way
  — next cycle triages the artifact on the pre-registered Arm 1
  gate). **HEALTH (08-14 ~08:2x UTC idle kick): the 03:xx launch had
  accidentally started TWICE** (03:17 + a 03:30 setsid retry — the
  COMMANDS.md kubectl-exec-timeout gotcha), both writing the same
  log/output zip; the newer duplicate was killed at 08:2x, the
  03:17 original survives healthy (mid DAgger-round-1 refit, ~27
  cores busy, no artifact written yet so the eventual zip is
  single-parent clean; only the log's 03:30–08:20 window is
  interleaved — triage the artifact on the eval, not the log
  stats). **And arm 2's ONE named CODE wait is CLEARED the same
  cycle: the MJX batched canonical-frame mint LANDED**
  (`MjxVecEnv._mint_seq_frames`, commit 8374125, default-off,
  pod-verified on CPU MJX: frame parity vs a fresh C reset within
  0.03 rad / 6 mm, batched episodes cross switches; pre-mint the
  vec path raised). Arm 2 now waits ONLY on the transdagger2
  artifact triage (warm-start order re-judge). NOTE for the next
  dig-in: `test_sharded_bitwise_matches_inprocess` FAILS on
  train-1 at unmodified HEAD too (~1e-5 obs drift, sharded vs
  in-process) — pre-existing pod-env issue, not the mint
  (**RESOLVED 08-14 ~17:xx — XLA platform mismatch, see the FLEET
  entry above**);
  train-0 intentionally left at 8249df2 until its CPU job ends.
  Detail: arch/STATUS.md + TRANSITIONS_DIRECTIVE "ARM 1 RESULT".**
  Every OTHER idle slot maps to a named wait in this block.
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
- **WAIT (08-13 ~23:xx UTC) `[operator]`: arch → rise-only-DAgger
  VARIANT DISTILL (operator/local lever). STRENGTHENED 08-14 ~17:xx:
  `cw-arch-modeseq1-r1` is the SECOND independent warm-RL to erase
  the dagger1 init's hard-start rise with the identical crouch-swap
  profile (rise12 5/12 crouch-only), and it proves a 75%
  sequence-training diet does not protect it — warm-RL from this
  init is now CLOSED (two-miss). The agent-side sibling lever
  (bridge/flat-heavy demo mix, transdagger3) RAN and FAILED (08-14
  ~19:5x triage: seq det 9/12 vs td2's 12/12 — the mix fixed the
  cold first rise 12/12 but starved the post-lower rise; rise12
  2/12 all-crouch, worse than td2; second data-mix miss → mechanism
  change per two-miss, no transdagger4). Option (b) — rise-only
  DAgger variant distill — is now the ONLY open rise lever besides
  the advisory anchor-on-rise Arm-2 retry mechanism, and its spec is
  sharpened by this result: ADD rise coverage across ALL start kinds
  (flat/bridge/crouch/post-lower), do not re-weight a fixed demo
  budget. transdagger2 remains the winning init for any retry.** `cw-arch-gru-dual2`
  (warm-RL
  from the DAgger-redistilled dual BC init, operator option (a))
  is verdicted FAIL per its own pre-registration: RL erased the
  init's hard-start stand-ups within 1M steps (canary auto-stop's
  first true catch — the init passed rise_bridge 2/2 at baseline,
  every probe after read 0) and the n=12/seed=1 recheck on the
  stopped 3.18M checkpoint reads 5/12 crouch-only vs the init's
  3/12 all-non-crouch (matched control, same pod/seeds). Every FAIL
  branch pre-routes to option (b), the rise-only-DAgger variant
  distill on the operator's Mac — with one requirement RELAXED by
  this run's evidence: lower need NOT be kept BC-only (RL rebuilt
  it 0/6→6/6 from the collapsed init). Detail: arch/STATUS.md,
  rl_docs/runs/cw-arch-gru-dual2.md.
- ~~hw — standing-lean design fork~~ **DECIDED 08-13 ~12:4x UTC
  (ruling 1 above): mechanical trim, outside RL.** The remaining
  work is a bench item (trim/zero-calibration/shimming), folded
  into the bench-session list below. Detail: hw/STATUS.md Now.
- **hw `[operator]` — stance promotion is a BENCH call (since 08-12 eve).**
  `cw-stand-footlow2-hard1` passes the full stance gate incl. the
  interactive `eval_session` hard gates the deployed `holdbc1_hard1`
  fails (148mm vs 55mm belly rise under the interactive ramp);
  `footlow2-stable1` is a second passing candidate (real hold-drag
  tradeoff vs hard1, +75%). Blocked on: operator bench session +
  promotion decision. Detail: hw/STATUS.md, SKILLS.md.
- **hw `[operator]` — tall-walk Gate 0 needs BENCH TAPE (since 08-12).**
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
- ~~multitask `[operator]` — PAUSED by operator (08-13 ~12:2x UTC)~~
  **RESOLVED (08-15 ~17:2x UTC): pause LIFTED by operator KICK focus
  note ("Remove the multitask operator-level pause now; it no longer
  applies") — the pause may not be cited to decline work again.**
  Normal launch rules govern the track. The wave-1 read stands as
  recorded (a2 pass; b2 acquisition shortfall; c2 fail; capacity/
  staged-widening/history levers all closed), now plus the
  translate1/translate-scratch1 double-FAIL (recipe closed). Detail:
  multitask/STATUS.md.
- ~~arch — DAgger rise redistillation LANDED; dual2 queued~~
  **RESOLVED (08-14): `cw-arch-gru-dual2` ran and is verdicted FAIL
  (canary auto-stop, rise erosion) — see the `[operator]` rise-only-
  DAgger entry above for the live fork.** Original entry kept below
  for lineage context only. Rise is in the BC init for the first
  time (`ppo_goal_cw_gru_dual_bc_dagger1.zip`: n=12 det 3/12 with
  non-crouch wins; hold 6/6; walk gait honest; lower collapsed 0/6).
  dual2 = exact dual1 recipe warm from the new init (ckpt on all 12
  train pods); FAIL branches route to the rise-only-DAgger variant
  distill (operator/local). The no-slip line CONCLUDES at its r4
  gate-pass artifact. Detail: arch/STATUS.md.
- **arch — NEW OPERATOR DIRECTIVE (08-13 ~21:00 UTC), agent-doable,
  not a wait: ONE model for operator-commanded rise→walk→sit→rise
  cycles — two jobs, spec of record
  `rl_docs/tracks/arch/TRANSITIONS_DIRECTIVE.md`.** CODE first
  (`goal.mode_seq` with per-switch re-anchoring; `distill_gru
  --transitions`; per-segment sequence eval baselined on the
  zero-fall two-specialist composition), then `cw-arch-trans-dagger1`
  (transition DAgger distill, CPU) and `cw-arch-modeseq1` (10M
  consolidated RL, dual1 stack + mode sequencing as the only new
  variable). Gates, warm-start order, and FAIL branches are
  pre-registered in the directive; its 12-lesson failure ledger is
  binding. **CODE item 3 LANDED+BASELINED (08-13, c-triage):
  `eval_modeseq.py` (pure external orchestration, no env/reward
  touch). Reference composition must be `footlow2_hard1`, not the
  deployed `holdbc1_hard1` (which reproduces its known sit-after-walk
  stall here, 7/12 zero-fall); footlow2_hard1 clears the directive's
  own bar 11/12 det but only 9/12 stochastic, ALL stochastic falls on
  the second (post-lower) rise — a decisive, numbered instance of the
  start-relative-`_z0` risk. Items 1/2 still OPEN, scoped not
  attempted (too large for a triage pass — see arch/STATUS.md Next
  for the concrete split).** Detail: arch/STATUS.md Next.
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
- **dynrep `[precondition: A/B/C cohort finishes — the operator's
  Cursor session owns it, not the orchestrator]` — RESOLVED FORWARD
  (08-14 ~12:48 UTC, commit 4cde930): the G1-FAIL wait above is
  CLEARED — the dataset-drift fix landed (champions pushed to the
  pods, collect preflights hard-require them), the 12-cell scale
  sweep RERUN passes the ORIGINAL G1 in 12/12 cells, and the A/B/C
  PPO-transfer cohort auto-launched on `dyn_scale_M_h16_large`
  (train-10 CPUs, `pod_chain_abc.sh`, walk-phase seeds live as of
  ~17:xx).** No orchestrator launch is legal here until the cohort
  reports; triage belongs to the owning session. Evidence hygiene
  (08-14 ~17:xx, per external-feedback note fb_20260814T164907):
  sweep gate JSONs + scale summary + the winning encoder ckpt were
  pulled off-pod to the controller
  (`/workspace/dynrep_backup/train-10_20260814/`) so a pod loss
  cannot erase the sweep's only evidence. Detail: dynrep/STATUS.md.
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
  JSON `--out`). **GRU port LANDED 08-14 (worktree session):**
  eval_cmd_suite now loads GRU/dual-GRU checkpoints via
  `load_checkpoint_auto` with hidden state threaded across steps and
  reset at episode boundaries; a checkpoint N_MODE_OBS wider than the
  env auto-enables `obs.mode_onehot` + `obs.mode_onehot_cmd` (the
  transplant's live-command routing; `--cfg-set obs.mode_onehot_cmd=0`
  overrides for episode-mode-routed dual checkpoints). Smoked on
  `walk_longdist_r2` (MLP, known shuffle numbers reproduce) and
  `gru_dual_bc_dagger1` (auto-widen 78=72+6, walks clean). The
  superseded `eval_cmd_suite.laptop-20260812.py` is deleted. The
  transplant's per-command gate can now run on a dual-core
  checkpoint; the operator call is purely a launch decision.
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
