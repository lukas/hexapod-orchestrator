# STATUS — two walking goals, each in sim and on hardware

Goal structure clarified by Lukas on 2026-09-08. Operator-facing digest,
not a live fleet snapshot. `RL_GOALS.md` owns purpose/priorities;
`CURRENT_TRUTHS.md` owns accepted operator rulings/durable contracts;
track `STATUS.md` + `ops.sh index story/lineage/promising` own run-level
detail and current history — read those, not this file, for "what
happened." Deployment control rate is **50 Hz** (hexapod2's MCU bridge
trips a timing fault above it); 100 Hz experiments are sim-only and
cannot be promoted for transfer (CONTINUITY RULE, orchestrator prompt).

## Parent outcomes

1. **`any_means`** — smooth joystick walking in sim and physically by
   any effective means (scripted/searched/demonstration-assisted/
   learned/composed). Methods: `joystick`, `amp`, `cpg`, `standwalk`,
   `assistfade`, `todaypolicy`.
2. **`rl_only`** — the same outcome, learned entirely through RL with no
   demonstrations anywhere in the walking policy's training lineage.
   Method: `walkcurr`.

Both proceed in parallel. Each needs an interactive joystick sim demo
with viewable video/reproducible launch path AND a bounded recorded
physical joystick trial (`RL_GOALS.md`). Report sim and hardware
readiness separately; sim progress is not held for hardware completion.

## Sim-demo readiness

**`any_means` — `todaypolicy-50hz-v1`** (`todaypolicy/bundle_50hz_v1/`):
all-learned stand/lower + 50 Hz walk. Interactive HTTP joystick capture
PASS: 0 falls/rejections on every phase incl. reverse (a demo-tool
timebase bug that made reverse look soft was found and fixed 09-10,
`CURRENT_TRUTHS.md` 09-10 "ROOT CAUSE + FIX"). A turn-capable alternate
walk role's turn-in-place freeze is fixed end-to-end by a non-RL
scripted-teacher composition wrapper (`--compose-turn-blend-s`, default
off, 09-12) — recommended for any session needing joystick turning on
this bundle. GO bundle; transfer manifest + trial plan packaged, Robot
Lab owns the physical session.

**`rl_only` — two composed candidates, both 100% clean-RL lineage (no
BC/AMP/demo/gait-clock in any component), both sim-only so far:**
- `bundle_rlonly_lifecycle_v2`: rise -> hold -> full-direction walk ->
  controlled lower, 3 independently-trained checkpoints (stance
  `currentcap29-s5-klrollback05-acq15m`, walk `slew_smooth_s0`, lower
  `thermalderate50-s2`). The lower component was ADOPTED 2026-10-06 — a
  per-joint actuator torque-capacity derate under sustained current (an
  env-dynamics mechanism), the one lever that beat baseline after 15
  closed reward/obs/architecture/margin mechanism classes targeting the
  lower role's L2+L5 terminal-support over-current habit. Composed
  direct-arm `lower_ok` 95.6% (153/160) across all 8 headings, flat, no
  off-axis collapse; residual failures are height-miss/rare tilt, not
  falls or the old over_current signature. Rise+walk alone: 0/320
  handoff falls across all 8 headings. Known limit: each role's own
  motor/safety contract differs, so a physical runtime must switch
  contracts at each handoff (not yet built). No turn role in this
  bundle. Manifest: `todaypolicy/bundle_rlonly_lifecycle_v2/`.
- `bundle_rlonly_curvewalk_v1`: composes the same walk role with an
  independently-trained turn-and-hold role (`walkyaw ... acq5-
  seedsweep-s5`) for real stationary turning and simultaneous
  turn+translate curved walking, full 8-way heading coverage: 0 falls
  across 124 episodes / ~236 segments. Includes a built, rendered,
  reproducible **interactive-script joystick demo video**
  (`joystick_demo1.mp4`, 7-segment forward/turn-left/forward/turn-right/
  reverse/curve-left/stop script, `rl_move/sim/joystick_demo_compose.py`)
  — the sim half of the RL_GOALS demo requirement for this candidate.
  Known limit: no rise/lower grammar (mode stays "walk" throughout); a
  2/48 single-leg-unload-during-hold quirk in the turn role (its own
  stance asymmetry, non-gating, 0 falls). Manifest:
  `walkcurr/bundle_rlonly_curvewalk_v1/`.

No single checkpoint/manifest yet stitches rise+walk+turn+lower in one
session (lifecycle_v2 has no turn; curvewalk_v1 has no rise/lower) —
both pieces are proven independently and share the same walk role.
Neither has had physical robot motion. Robot Lab briefing for the
current lower-role candidate: expect occasional (~1-in-20) height-miss-
without-fall or tilt_roll, not the old ~1-in-4 over_current stop.

Full derivations/history: `walkcurr/STATUS.md`, `todaypolicy/STATUS.md`,
`ops.sh index story <bundle-or-checkpoint>`, `CURRENT_TRUTHS.md` 09-10 /
09-17 / 10-06.

## Recorded method milestones — not parent-goal completion

- `joystick`: GREEN 08-23 at the legacy 60 s randomized MuJoCo gate
  (`stotight45-seed13`, zero falls, 25 Hz primitive family) — this is
  the track's CORE DONE GATE; later 100 Hz/mesh work is operator-ordered
  polish, not gate-blocking. Physical drive goes through Robot Lab.
- `amp`: GREEN 08-23 at sim-transfer M5 (`phasehz11_s29`, demonstration-
  assisted); M2 (style reward improves gait quality) is CLOSED null on
  both from-scratch and warm-started routes. Hardware M6 goes through
  Robot Lab under Goal 1.
- `cpg`: GREEN 08-23 at the contextual walk/turn/stop gate (`robust120-
  winner-yawtrim` incumbent stands).
- `walkcurr`: both sim-demo candidates above; the 16-lever lower-role
  investigation and the full-direction walk/turn roles are the
  headline 2026-10 results (see Sim-demo readiness).
- `standwalk`: deployable-width (tf64l2h16/tf128l2h16) DR/actuator-robust
  walkers exported, but every variant tried is fixed-heading-only (FAILs
  the randomized joystick DONE-gate on slip/dir_err; stress_mix fine-
  tune and its follow-ons are closed 0/8+). Packaged for a bounded
  fixed-heading Robot Lab trial, not omnidirectional joystick-ready.
- `assistfade`: the whole fade-assist-to-full-authority mechanism family
  (~47 arms, PPO+SAC) is closed — 0 clean ignitions except the
  persistent BC-anchor rung 0, which stays production-usable (assisted
  ancestry, Goal 1 only).
- `todaypolicy`: owns the named `bundle_rlonly_*`/`bundle_50hz_v1`
  composition manifests above; see `todaypolicy/STATUS.md` for the
  current component swap history.

Registry: `orchestrator/tracks.json`. Method evidence and queues:
`rl_docs/tracks/<track>/STATUS.md`. No closed recipe is reopened by this
digest; there is no requirement to make every method green.

## Ownership and actual waits

Cloud cycles prepare sim evidence and controller handoffs; Robot Lab owns
serialized physical experiments under standing authority and live
camera/telemetry/abort rules. Routine calibration/bounded motion/
deployment are not blanket operator blockers; only hands-on needs or
spend/capacity increases beyond guardrails are operator waits.

WAITING-ON (refreshed 2026-10-06):
- `[operator]` raw PS200 per-joint telemetry export still wanted for the
  `speed` track (fitted current model + divergence summary landed
  09-20, not the raw traces). Every named joint/correlated/asymmetric
  mechanism and the transient foot-catch event are closed FAIL/NULL as
  of 09-20; no further cloud-originated speed-track roll-mechanism arm
  is justified until new telemetry or a genuinely new structural idea
  appears (`speed/STATUS.md`).
- `[Robot Lab]` bounded physical joystick trials of the GO/evidence
  bundles: `todaypolicy-50hz-v1` (any_means, GO), `bundle_rlonly_
  lifecycle_v2` (rl_only, rise->walk->lower, 95.6% full-direction,
  accepted 2026-10-03/06 as sufficient for a guarded trial), and
  `bundle_rlonly_curvewalk_v1` (rl_only, walk+turn, 0 falls/124
  episodes, has an interactive sim demo video) — transfer manifests and
  briefings packaged for all three; none has had physical motion.
- `[Robot Lab]` `standwalk`'s fixed-heading-only deployable exports
  (tf64l2h16/tf128l2h16 ceil20, profilewrite2000, yaw_contract_phaseclk,
  `contract2000-s0` stand role) are DR/actuator-robust but all FAIL the
  general randomized joystick DONE-gate (legacy fixed-heading training
  distribution, stress_mix fine-tune closed 0/8+) — candidates for a
  bounded FIXED-HEADING trial only, not omnidirectional joystick
  control. `ops.sh index promising --track standwalk` lists every
  exported checkpoint.

Resolved since last refresh (left here so nobody re-reads the old
framing from a cached copy): the `walkcurr` `lower`-role achievability
question (16/16 mechanism classes closed as of 09-17) is ANSWERED — the
17th family (`motor.thermal_derate_enable`) passed a 3-seed population
10-06, see Sim-demo readiness above. The `walkyaw` turn-in-place freeze
(09-18, 27/27 closed, parked on an operator scope ruling) is also
superseded — the later `bothleggate`+`yaw_offset` SAC recipe
(`acq5-seedsweep`) finds real stationary turning + curved walking
cleanly (now the turn role in `bundle_rlonly_curvewalk_v1`); no operator
ruling was needed in the end.

## Doc rules

Keep under ~160 lines (compacted 332->161 on 2026-10-06; prior text:
`git show 854618d:STATUS.md`). Replace stale status; put history in
`RL_LOG.md`, track `STATUS.md`, and the ledger (`ops.sh index`). Do not
infer current fleet activity from this digest.
