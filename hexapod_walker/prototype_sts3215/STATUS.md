# STATUS — how is it going?

Plain-English answer to "how is it going, what can the robot do now,
and what big things have we learned?" — for the operator or anyone
catching up. No jargon-first: every claim links out to the file with
the evidence. Facts here must agree with `CURRENT_TRUTHS.md` (which
wins on conflict); checkpoints and gate numbers live in
`rl_docs/SKILLS.md`.

**Last updated: 2026-08-11.**
Update rule: refresh this file whenever a hardware session happens, a
new capability lands (SKILLS row that changes the story), or a big
lesson closes — and stamp the date. Keep it honest: the "not working"
list is the most valuable section.

## The one-paragraph answer

The real robot walks — under a scripted gait, not a learned one yet.
In simulation we have a hardened, seed-confirmed joystick-driving
policy stack and a validated hardware-deployment candidate staged on
the Mac, waiting on bench time (and one servo-zero repair). Standing
up honestly (not faking it) just had its first real breakthrough
(08-11, `cw-stand-bc1` — see below) after six straight reward-tuning
failures; obeying turn commands is still unsolved (policies drift
left and ignore the yaw channel). Turning got new machinery this
cycle (mirror-symmetry training, new turn pricing) that passed the
offline semantics checks — and it was then actually trained and
FAILED: the new turn reward changed nothing measurable versus the
already-failed policy it was compared against. Standing, by
contrast, needed a different kind of fix (coaching the actions
directly instead of tuning the reward) and that fix worked.
Tuning the reward numbers for either skill is now a dead end; both
need a structural fix, not another price change (see below).

## What the robot can do — REAL hardware

- Walk forward, crab sideways, and turn in both directions from a
  clean zero, under the scripted tripod gait. Measured with a tape:
  it covers ~50% of commanded distance (real slip, and that's fine —
  visible slip is part of how it locomotes).
- Walking is CHEAPER than standing still (0.33–0.45 A vs 0.59 A) —
  a genuine surprise that reshaped our effort-pricing assumptions.
- A learned policy has NOT yet driven the robot. Attempt #2's
  checkpoint (`cw-dep-vref1-r1`) is validated in sim under the exact
  deployment contract, protected against ~20 hardware-imperfection
  axes (sensor noise, latency, battery sag, assembly tolerances —
  all compose free), and staged on the operator's Mac. Blocked only
  on bench time (start with a fresh `set_zero`, as always).

## What the robot can do — simulation

- **Joystick driving**: walk at commanded speed (up to 0.06 m/s),
  steer anywhere in the front half-circle (±90°), stop and restart,
  survive abrupt command flips, for up to 2-minute drives with zero
  falls — robust to physics variation (DR 0.5), bus latency, floor
  grip, 3° slopes, payload, and off-center mass, seed-confirmed.
  Caveat: it's a paddling gait that slips ~1 m per meter traveled.
- **Crouch walking** down to −70 mm body height; rough ground
  (bumps to 36 mm) doesn't perturb it.
- **Stand up and drive** works as a three-piece demo (sim-proven,
  key `7` in `sim_viewer/sim_play.sh`): stance policy rises from the
  belly → scripted 1.5 s blend → walk policy drives. What we do NOT
  have is one policy that does all of it.
- **Four-leg stand** (party trick #1) holds solid — but training it
  mixed with walking erodes the walk, so it stays a deploy-time
  specialist.
- Full inventory with checkpoints and evidence: `rl_docs/SKILLS.md`.

## What is NOT working (the honest list)

- **Unified stand-up (the top unsolved skill).** Every training
  attempt finds a cheat: torso at height with legs waving, tripod
  stands, stilts. A geometric "valid plant" spec (feet down, CoM
  inside the support polygon, level, walkable footprint) landed
  08-10 — but pricing it live into training (`cw-stand-plantgate1`)
  did NOT stop the cheat: same one-leg-up flag-leg stand, 0/12 valid
  plant, identical to the pre-detector baseline. We then tried
  rebuilding the income from scratch around a "stand score" instead
  of just gating the old terms (`cw-stand-score1`, 08-10 night) —
  even started clean from the honest stance champion, it converged
  right back to the same one-leg-up trick, 0/12 valid plant across
  easy and hard starting poses. We then tried the other idea we had
  left — showing the policy a real recorded stand-up motion to copy,
  built so the cheat can't collect payout for faking it
  (`cw-stand-scoreref1`, 08-11) — and it ALSO failed: same leg held
  16-19cm in the air the whole episode, 0/6 valid plant every mode.
  A bug was briefly suspected of causing that whole streak (the
  simulator's episode-reuse code was silently corrupting the
  score-tracking state those fixes depended on) — fixed, and the
  clean re-run (`cw-stand-rsi2`, 08-11) reports: the fix worked (its
  internal health checks are clean this time, no more corruption)
  and it STILL learned the identical cheat — three legs planted,
  three legs frozen 15-16cm in the air, 0/6 by our strict check.
  So the bug was real but was never the reason stand-up fails. One
  more variant (`cw-stand-rsi3`, 08-11: strip out an old penalty
  term that might have been making the honest crouch look
  artificially expensive) also failed, identically. **Every
  reward-design idea we had is now exhausted, and the pattern across
  all six attempts is the tell**: the same three-legs-frozen collapse
  happens at the same point in training no matter which reward
  mechanism or penalty is present — a behavior that doesn't change
  when you change the reward isn't a reward problem. Best read: the
  training recipe starts the robot in a body position it never
  practiced enough (a warm-start gap), and early noisy updates drift
  it into the frozen-leg trick before anything can pull it back out.
  The first of the two code ideas is now BUILT and TRAINING (08-11):
  a "copy the recorded stand-up motion directly" hand-hold in the
  trainer itself — at every step of a stand-up episode the policy's
  action is pulled toward what the recorded good stand-up did next,
  a supervision signal the cheat cannot farm because it isn't reward.
  **It worked (08-11).** The first trial (`cw-stand-bc1`) is the
  first arm in seven straight attempts where the robot genuinely
  stands up on real video, checked with a strict feet-on-the-ground
  geometry test (not just the height number the old cheats gamed):
  from a half-curled start it stands correctly most tries, and from
  lying completely flat on its belly (the hardest, most realistic
  starting position) it reaches a real six-legged stand every single
  time. Zero fake one-leg-up stands seen in
  42 checked videos. A quick check of a gentler dose of the same
  coaching made things worse, not better (dose must stay at full
  strength). Training the same recipe for longer made the honest
  stand even more reliable (strict check: 12/12 across every
  starting pose, and the flat-start "feet slightly off the walking
  spot" gap fixed itself with the extra budget) — the long run is
  now kept as the official STAND-UP SPECIALIST checkpoint. A
  careful side-by-side re-test of the shorter run under identical
  conditions confirmed the longer training broke nothing that
  previously worked. But digging into the per-step
  data (not just watching video snapshots, which missed this) found
  that "holding still" was never actually still: the robot quietly
  shuffles its legs the whole time instead of standing motionless,
  and training longer made that shuffling MORE pronounced, not less.
  This looks like a separate, pre-existing gap in how we reward
  staying stationary, not a side-effect of the new coaching itself —
  it needs its own proper fix before training this recipe further.
  `rl_docs/RISE.md`.
- **Turning on command.** Walk policies carry a structural left-yaw
  drift and ignore the yaw command channel; raising the price of
  drift failed repeatedly, and a second, better-designed reward
  mechanism also produced NO measurable change head-to-head
  (`cw-walk-turnfix1`) — reward tuning for turning is closed twice
  over; the drift looks baked into the walking gait itself. The next
  lever, mirror-symmetry training (penalize the policy for treating
  its left/right sides differently, `rl_docs/TURN.md`), landed
  08-10 night: a quick mechanism check (`cw-omni-mirror1`) confirmed
  the symmetry penalty actually takes hold during normal training
  (asymmetry signal fell to under half its peak, reward climbed
  fine). The follow-up 40M-step hardening run (`cw-omni-mirror1-r1`,
  08-11) did NOT test the mirror-symmetry hypothesis either way: the
  walk gait itself collapsed into standing almost still (forward
  travel 0.68 m -> 0.01 m per episode vs the same recipe without
  mirror, half the episodes with stuck/frozen legs) because standing
  still scored HIGHER than walking — a reward bug, not a turning
  result, and mirror-symmetry is still UNKNOWN. The bug is now found
  and FIXED (08-11): during "turn in place" commands the
  speed-tracking reward paid a motionless robot its full income (zero
  speed matched the zero speed command perfectly, and the gate that
  normally stops that only watched straight-line walking), so
  freezing out-earned imperfect walking by construction. The reward
  now pays that income only in proportion to how much of the
  commanded turn is actually achieved, an offline check bank pins the
  exploit forever, and the 40M hardening run was relaunched with only
  that one change (`cw-omni-mirror2`). Result (08-11): the specific
  freeze bug is confirmed fixed — walking now earns more than
  freezing — but the gait still breaks down about half the time into
  a different bad habit (one or more legs held stationary in the air
  or planted and never moved, barely inching forward), so
  mirror-symmetry is STILL unanswered. Next move is not another
  mirror training run; it's finding what still pays for that
  leg-sacrifice habit. A DR-strength check (`cw-omni-mirror2-dr02`)
  and a turning-removed variant (`cw-omni-trans1`, walking in any
  direction with the turn-in-place logic dropped entirely) both
  failed the same way — trans1's failure looked different again
  (legs churning rapidly almost in place, two legs stuck planted,
  body barely traveling), a third distinct collapse pattern. Turning
  itself has been DE-SCOPED from the joystick deliverable (no camera
  = no reason to need a "front"), so this line now serves only the
  any-direction-walking goal.
- **Backward walking** — parks or falls; envelope is the front
  half-circle only.
- **Sim effort realism**: sim under-prices standing still (0.11 A
  vs the real 0.59 A) — needs a holding-current model fit before
  effort-shaped gaits can be trusted. Servo LAG realism, by
  contrast, is now validated end-to-end (08-11): training with the
  measured under-load servo response (real servos take ~0.3 s to
  settle a 2° step, not milliseconds) keeps the walking skill intact
  and even slightly beats the old champion when both are judged
  under that honest physics (`cw-dep-vref1-loaded1`) — the earlier
  "it got 40% worse" read was just comparing against scores from the
  old instant-servo physics.
- **Learned gait quality**: the champion "walks" by paddling with
  loaded-foot slide; acceptable in sim scoring, but the real robot's
  scripted gait remains the quality bar.

## Big things we have learned

1. **Reward hacking is the default outcome, not the exception.**
   Every under-specified reward got gamed: freeze-and-collect (alive
   bonus), park-and-earn (velocity kernel), flag-leg stands (height
   term), cadence inflation (step credits). The countermeasure that
   works: make cheats earn ~0 BY CONSTRUCTION (income gating), never
   just charge for them — additive penalties get priced in and paid.
2. **Cheap tests before expensive training.** Scripted-trajectory
   semantic banks (MDP_PREFLIGHT) catch reward bugs in minutes that
   used to cost 20M-step runs; now binding before any launch.
3. **Hardware truth keeps overturning sim assumptions.** Walking is
   cheaper than standing; slip is locomotion, not failure; a "10°
   tilt = fall" rule was far too strict (real gait rocks ±10–20°);
   loaded servos respond ~30× slower than the air-only fit. Every
   one of these forced a sim or reward fix.
4. **Single-axis robustness training is mostly worthless here.**
   12-for-12 sensor/calibration noise axes: exposure training bought
   nothing the champion didn't already have for free. The ~20-axis
   protective sweep on the deployment candidate found essentially no
   real regressions — that whole class is now CLOSED.
5. **Controls need matched baselines.** A child policy evaluated
   under an injected perturbation must be compared against its
   parent under the IDENTICAL injection — two "failures" reversed to
   PASS once the control was run properly.
6. **Skills interfere.** Quad-hold mixed into walk training erodes
   walking; stand-different-heights and walking live in different
   stances. Composition (blends, specialists, curricula) beats
   naive multi-task mixing so far.
7. **Wrong logical zeros are how hardware gets destroyed.** The
   08-06 incident (tipped robot, cooked servo, shorted rail) came
   from software poses commanded against a stale zero frame —
   hence the hard safety rules in AGENTS.md.

## What happens next

1. Hardware attempt #2 with the staged `cw-dep-vref1-r1` checkpoint
   (joystick walk on the bench, fresh `set_zero` first).
2. Reward tuning for standing is closed by trained evidence (six
   mechanisms tried, all cheated); the fix that worked instead
   coaches the policy's actions directly (`cw-stand-bc1`, 08-11) —
   two follow-ups running to see if it holds up over more training
   and whether a gentler dose removes its small side-effects. Reward
   tuning for turning is also closed; its structural next move
   (mirror-symmetry augmentation) is landed but every hardening
   attempt has collapsed into a different gait pathology before
   testing the real hypothesis — turning is de-scoped from the
   joystick deliverable for now (no camera, no "front" to need).
3. Sim effort-pricing fix (holding-current model) so effort-shaped
   arms become trustworthy.
Queue and blockers: `RL_PLAN.md`.
