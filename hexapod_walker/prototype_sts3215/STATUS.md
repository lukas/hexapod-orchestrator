# STATUS — how is it going?

Plain-English answer to "how is it going, what can the robot do now,
and what big things have we learned?" — for the operator or anyone
catching up. No jargon-first: every claim links out to the file with
the evidence. Facts here must agree with `CURRENT_TRUTHS.md` (which
wins on conflict); checkpoints and gate numbers live in
`rl_docs/SKILLS.md`.

**Last updated: 2026-08-10 night.**
Update rule: refresh this file whenever a hardware session happens, a
new capability lands (SKILLS row that changes the story), or a big
lesson closes — and stamp the date. Keep it honest: the "not working"
list is the most valuable section.

## The one-paragraph answer

The real robot walks — under a scripted gait, not a learned one yet.
In simulation we have a hardened, seed-confirmed joystick-driving
policy stack and a validated hardware-deployment candidate staged on
the Mac, waiting on bench time (and one servo-zero repair). The two
big unsolved skills are standing up inside the walking policy (every
attempt so far games the height reward) and obeying turn commands
(policies drift left and ignore the yaw channel). Both got new
machinery this cycle (a geometric standing-plant check, new turn
pricing) that passed the offline semantics checks — and both were
then actually trained and BOTH FAILED: the standing check didn't stop
the same one-leg-up cheat, and the new turn reward changed nothing
measurable versus the already-failed policy it was compared against.
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
  easy and hard starting poses. Three differently-designed reward
  fixes have now lost to the identical cheat; tuning what the reward
  pays is a dead end for this problem, not an unlucky run. Next
  lever has to be outside reward shaping (bringing back trajectory
  guidance, or tying the height command to real foot contact).
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
  fine), so a full 40M-step run (`cw-omni-mirror1-r1`) is now
  training the real omnidirectional/turn behavior under that rule.
  Still UNKNOWN whether it cures the drift — that verdict needs the
  finished run's turn-tracking numbers and video against the walking
  champion.
- **Backward walking** — parks or falls; envelope is the front
  half-circle only.
- **Sim effort realism**: sim under-prices standing still (0.11 A
  vs the real 0.59 A) — needs a holding-current model fit before
  effort-shaped gaits can be trusted.
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
2. Reward tuning for both turning and standing (three rise
   mechanisms tried) is closed by trained evidence, not just
   prediction. Turning's structural next move (mirror-symmetry
   augmentation) is landed and already training — a 40M-step run
   (`cw-omni-mirror1-r1`) is underway, verdict pending. Rise's next
   move (reference tracking or foot-contact-coupled height) is still
   a SPECIFICATION step — no code landed yet.
3. Sim effort-pricing fix (holding-current model) so effort-shaped
   arms become trustworthy.
Queue and blockers: `RL_PLAN.md`.
