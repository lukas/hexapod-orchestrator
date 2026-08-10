# What we are doing, in plain English

We have a real six-legged robot (hexapod, STS3215 servos) sitting in
the operator's house. We are training neural-network controllers for
it in a physics simulator (MuJoCo), on cloud GPUs, with an
autonomous loop of AI agents that design experiments, watch them
train, judge the results honestly, and launch the next one.

**The end goal (operator, 08-10): drive the robot around the room
with a joystick — it stands up, sits down, turns, and walks where
you point, reliably. Then the tricks: stand on four legs, walk on
four legs.** Sim numbers only matter insofar as they get us there.

## What "good" means (operator's own words)

Distance, stability, reliability. The robot should cover real
ground, stay level, and never fall. A policy that walks 0.6 m every
time beats one that walks 1 m or falls at 50/50. Speed targets are
a means, not the objective. Foot slip is not failure by itself —
the scripted gait that walks the real robot slips visibly (08-09);
slip metrics exist to keep sim honest about the real floor, not as
a ban.

## Where we are (update this when it changes — keep it plain)

As of 2026-08-10 (midday — supersedes the 08-09 notes below where
they disagree): the REAL robot walks under a scripted gait; the
learned sim gait works but creeps (contact pricing calibration
pending — 08-10 tape sessions measured real slip ratio 0.50-0.51,
and a loaded-actuator model refit is in progress in a parallel
operator thread); the sim joystick driving stack is hardened and
seed-confirmed; turn-in-place passed the joystick gate (yaw-tracking
metric still needs custom analysis); the four-leg trick holds
perfectly but erodes walking when mixed into training (4 data
points, not dose-proportional — goes to a deploy-time specialist,
not the training mix); stand/sit inside the walking policy is the
main unsolved skill — see "Standing up" below for the 08-10 findings
and plan; hardware attempt #2 base (cw-dep-vref1-r1,
deployment-exact obs) is validated and staged, and survived 9 of 10
single-axis robustness composes (payload/mass is the one non-free
axis). Operator hold on new agent launches until the actuator model
lands; agent is in triage-only mode.

## Standing up ("rise") — what we learned 08-10 and the plan

The unified policy could never stand up from the belly. Two
root-cause bugs were found and fixed (reward pricing paid FREEZING
more than trying; the walk-lineage warm start is measurably blind to
the height command channel). The fix arms (cw-uni-rfix-warm1/fresh1)
then showed a THIRD problem: the training reward pays for TORSO
HEIGHT only, so the fresh policy learned to hit the height with a
foot 30 cm in the air (bridge/flail) — it satisfied training's
criterion at "6/6" while the posture-strict harness scored it 0/6.
Longer training will not fix that; it optimizes the gameable
criterion harder.

What the stand-up literature does (HumanUP and HoST, RSS 2025;
HiFAR 2025): never learn a deployable get-up from a bare task reward
in one shot. Discover the motion once (loose limits, sparse reward),
then train the deployable policy to TRACK the discovered trajectory
under strong smoothness/torque regularization and randomization,
with posture-aware staged rewards and curricula (assistive force,
start-state expansion) as needed.

Our shortcut: the discovery stage is ALREADY DONE — the stance-line
champion (ppo_goal_cw_stance_dr10) performs a genuine feet-down
belly-rise on today's sim (re-verified 08-10: det flat start, ends
5 mm off target, worst pad clearance 4 mm). Landed 08-10 to exploit
that (all cfg-gated, default-off, default reward stream
md5-identical):

1. **Posture gate** (`reward.rise_posture_gate=1`): rise/lower
   income (milestones, finish bonus, post-ramp kernel) scales with
   the fraction of feet within 20 mm of the ground — "at height, on
   your feet" pays full; "at height, feet flying" pays ~nothing.
   Geometric clearance, matching the eval harness's end_posture_ok
   (not touch force — champions legitimately rest lightly on some
   feet). The existing `k_end_posture` penalty composes with it.
2. **Reference tracking** (`reward.k_rise_ref_track` +
   `reward.rise_ref_path`): dense joint-space kernel against the
   champion's recorded rise (`rl_move/sim/refs/
   rise_ref_stance_dr10.npz`, built by `extract_rise_ref.py`),
   time-aligned at the height-ramp start so jittered holds and
   crouch/bridge starts join the same reference. Verified: the
   champion earns ~full pay on its own reference, a frozen robot
   ~13%. A scaffold — run at full weight to seed the skill, anneal
   to 0 across arms so the final policy is not trajectory-locked.
3. **Walkable-height reference + targets** (operator ruling, 08-10
   ~11:00 ET: the champion's ~70 mm crouch-stand is "a terrible
   stand, we couldn't walk from that" — the deliverable is the
   ~142 mm plant stance the walk line lives in). `extract_rise_ref
   --blend-to-plant` appends the sim viewer's validated 1.5 s
   blend + a plant hold, so the reference ends WALKABLE:
   `rl_move/sim/refs/rise_ref_belly2plant.npz`, +111 mm over
   belly, all pads down, 7.4° RMS from plant. Commanding it needs
   `goal.rise_height_mm=[105,114]` (cfg-set now parses JSON lists)
   AND `actions.max_height_mm=115` (default 80 clamps below plant
   height — rises this tall were previously impossible to even
   command). Pricing smoke (`tmp_smoke_rise_ref.py`, full stack
   on): replaying the demonstrated path +952 vs stilt-exploit +225
   vs freeze −195 — trying-well >> trying-badly >> not-trying,
   with not-trying net NEGATIVE. First arm: `cw-stand-b2p1`
   (queued, backlog).
4. **Control probe in flight** (`cw-stance-riseproof1`, launched
   08-10 ~15:00Z, operator): the stance-line joint_goal recipe,
   from scratch, same mix as rfix-fresh1, on today's sim. If it
   learns posture-strict rise where the walk-env arm gamed it, the
   walk-env task construction is implicated and the Stage-II
   tracking route (or two-policy blend) is the path; if it also
   fails, sim contact near the ground is implicated — dig in there
   before any more rise arms.

Fallback that already works: two-policy blend (stance policy rises,
scripted 1.5 s blend, walk policy drives — the sim viewer's "7" key
proves it). The joystick MVP does not have to block on the unified
rise. Big rise consolidation runs wait for the loaded-actuator model
(rise is a high-load motion; it is the behavior most sensitive to
that fix).

As of 2026-08-09 (~cycle 34):

- The simulated robot has a REAL walking gait — all six legs
  stepping in rhythm. That took ~30 experiments to get.
- The gait's feet SLIDE along the ground while "stepping"
  (paddling/skating). On the real robot that would go nowhere and
  grind the servos, so this is THE blocker to hardware deployment.
  We measure it as "slip per meter traveled" (want ≤1.0; best 1.24).
- We proved (cycles 24–36) that no reward bonus/penalty tweak fixes
  the sliding — the simulator makes sliding physically FREE, so the
  optimizer always prefers it (cycle 36 closed the last income-side
  lever). The operator's 08-09 design rulings landed (new metrics +
  gates in flight); the servo-current hardware calibration — the
  deepest fix — is still operator-owned.
- Standing up and lying down (heights) are solved under full
  randomization; the "posture" detail (one leg finishing in the
  air) is stuck behind the same pricing issue.
- The operator keeps a standing backlog of things to learn
  (turning, back-and-forth, driving, quadruped mode, five-legged
  walking, ...): `WISHLIST.md`. Idle pods pull from it.

## The cast

- **The loop:** a watcher script polls training; each finished run
  triggers an agent "cycle" that evaluates it (with video, not just
  scalars), writes a verdict, and launches the next experiment.
- **Runs** are named `cw-<line>-<idea>` (e.g. `cw-walk-anchortol5`);
  continuations get `-c1`, `-c2`. Everything is recorded in the
  ledger (`rl_move/orchestrator/experiments.json`) and W&B
  (`l2k2/hexapod-balance`).
- **Compute:** CoreWeave pods; 2 GPU pods train 20–40M-step runs in
  ~20–40 min (MJX), CPU pods handle probes and small runs.
