# STATUS — two walking goals, each in sim and on hardware

Goal structure clarified by Lukas on 2026-09-08. This is an operator-facing
digest, not a live fleet snapshot. `RL_GOALS.md` owns purpose and priorities;
`CURRENT_TRUTHS.md` owns accepted evidence. Consult the state ledger and
track journals for current run/queue status.

**UPDATE 09-10 (op_20260910_50hz):** deployment control rate is now
**50 Hz** — hexapod2's MCU bridge (18-servo read 9-13 ms + write
~4.4 ms) trips the timing fault at 100 Hz within 3-52 ticks, while
25 Hz ran 150 ticks clean; the 08-24 100 Hz order is superseded for
robot-bound candidates (CURRENT_TRUTHS top entry). A 5-arm 50 Hz
retrain fill (walk x2, turn x2, stand/sit x1) launched 09-10; every
PASS exports v2-stamped `--training-hz 50` artifacts into
`linux_control/policies/*50hz*` toward a 50 Hz todaypolicy bundle
(stand/lower + walk + turn). See standwalk/amp/todaypolicy STATUS.

## Parent outcomes

1. **`any_means`: smooth joystick walking in sim and physically by any effective means.**
   Scripted, searched, demonstration-assisted or learned controllers all
   count. Methods: `joystick`, `amp`, `cpg`, `standwalk`, `assistfade`, `todaypolicy`.
2. **`rl_only`: the same outcome, learned entirely through RL with no
   demonstrations anywhere in the walking policy's training lineage.**
   Method: `walkcurr`. BC/AMP/scripted-gait assistance belongs to
   `any_means`, even if assistance later ends.

Both proceed in parallel. Each needs an interactive joystick sim demo and
viewable video as well as physical walking evidence. Report readiness, demo
link/launch command and remaining limits separately for each deliverable.
Non-interactive reproducible sim video exists for a candidate under each
goal (below). **UPDATE 09-10:** the browser's own HTTP joystick API
(`/api/rl/...`) is headlessly drivable from a cloud pod with no display
(`web_session_drivecapture.py`) — the earlier "needs a display,
irreducible-to-cloud" read was wrong about that specific claim. Chasing
it found and fixed two real config-threading bugs (silently-clobbered
`joint_action_box`/`bias` and `walk_obs_body_vel` explicit overrides) and
one real tool bug (missing joystick heartbeat resend, now fixed).
**`rl_only` result:** interactive PASS on its champion below — 0 falls,
0 rejected commands, strong direction-correct translation on
forward/crab-right/diag-left/restart, but the **reverse phase is a
genuine, confirmed defect**: it nets only ~0.15-0.06 of commanded speed
in the commanded direction (two independent metrics agree closely),
despite real motion (magnitude ~0.5-1.0) — consistent with (not a new
instance of) the already fully-closed `walkcurr` 180-degree-heading
front-pair leg-sacrifice mechanism. **`any_means` result:** interactive
PASS with 0 falls/rejections on every phase incl. reverse; a
`web_session_drivecapture.py` timebase bug (this tool's phases were
scheduled on wall-clock while the server it drives over HTTP was
quietly stepping physics at ~0.26-0.87x real time, model-source
dependent) had made "reverse" look like a standout-soft, ~25%-
intermittent residual through most of 09-10's investigation — fixed
(phase transitions now gate on the server's own simulated clock), and
the properly-measured picture is a smaller, general (not reverse-
specific) softness on commands with no forward-velocity component
(crab-right now the weakest, reverse mid-pack). **Full derivation,
per-phase tables, and which earlier same-day numbers this supersedes:**
`CURRENT_TRUTHS.md` 2026-09-10, top entry ("ROOT CAUSE + FIX"). Physical
acceptance needs a named build/controller, a bounded joystick trial
with video/telemetry, and reported direction/speed/yaw/start/stop
limits; `rl_only` also needs clean training ancestry.

## Recorded sim-demo candidates and limitations

**UPDATE 09-11 (op_20260910_50hz):** the deployable `any_means` candidate is
now **`todaypolicy-50hz-v1`** (`rl_docs/tracks/todaypolicy/bundle_50hz_v1/`)
— `todaypolicy-mlpsf-tuck-v1` below is a 100 Hz bundle and 100 Hz trips
hexapod2's MCU-bridge timing fault (same supersession the `rl_only` bundle
below already went through). New bundle: all-LEARNED stand/lower (not
scripted `tuck`) + 50 Hz walk, demoed end-to-end this cycle
(`ops.sh hybriddemo`, full mesh, 0 falls, `walk_gait_valid=true`,
`walk_progress_ratio=0.402`, `cur_max_a=2.64A` in-contract). A validated
turn-capable alternate walk role (real wz authority) is registered too but
not the default (quality/robustness tradeoff, see the bundle's GO_NOGO) —
first time this gap has a named, passing candidate at all. **UPDATE 09-12:**
that turn-capable alternate's own real defect — a sustained turn-in-place
command freezes it into a static splayed crouch (a session-duration/action-
distribution gap, not a mass or reward bug) — is now FIXED end-to-end by a
non-RL scripted-teacher composition wrapper (`--compose-turn-blend-s`,
default off/bit-exact) validated on the actual checkpoint: full walk/rise/
lower/hold gate panel unregressed vs the uncomposed gate, plus a clean
20 s `human_turn` drivevideo (0 falls, `wz_err_med_rad_s=0.075`, real
per-frame leg reconfiguration). Composition is RECOMMENDED for any session
needing joystick turning on this bundle. See `todaypolicy/bundle_50hz_v1/
{GO_NOGO.md,composition.json}` and `amp/STATUS.md` 2026-09-12. **UPDATE 09-11
(mass-audit-bug fix):** the stand/lower residual named here through 09-11
~11:4x (1/12 rise over_current mixed-start; 2/12 tilt_roll own-DR 0.2,
closed short of PASS across pricing/pacing/budget/stacked-structural
levers) turned out to be a physics-model bug, not a real ceiling — the
checked-in mesh twin was 37.6% overweight (3.49kg real vs 4.806kg
trained/evaluated); with the twin corrected, the SAME `curhot-b23k12`
checkpoint (already shipped in `todaypolicy-50hz-v1`, zero retrain) reads
0/36 over `over_current` across the whole hold/rise/lower det+sto panel.
No unbuilt mechanism is needed for this residual; `reward.k_torque_headroom`
was built anyway (default-off, kept) but the bracket that tested it landed
on the same mass-bug-inflated floor as every other lever. See
`CURRENT_TRUTHS.md` 2026-09-11 ~12:1x and `standwalk/STATUS.md` 09-11 ~12:1x.

**`any_means` (historical): `todaypolicy-mlpsf-tuck-v1`** — 100 Hz bundle
PACKAGED 08-30 (all TODAY bars passing), superseded for deployment by the
50 Hz bundle above; interactive HTTP capture 09-10 PASS (3/4 reverse
repeats clean after the `_PlayTraj` command-blend fix). Evidence:
`todaypolicy/bundle_mlpsf_tuck_v1/`, `CURRENT_TRUTHS.md` 09-10.

**`rl_only`: `ppo_goal_cw_walkscratch_crutchoff_s0_widen8_legdutyratio_
swinggap_dose10_plusduty_acq1_cont10m.zip`** (walkcurr, no BC/AMP/demo in
lineage), recipe-default widen8 champion, durability-confirmed at 50M steps.
Reproducible non-interactive video (09-09, `ops.sh drivevideo ... --script
human[_turn]`): forward/crab-right/diag-left/reverse/**stop**/**restart**,
0 falls, `gait_valid=true`, `sacrificed_legs=[]` for the full 26 s episode.
Interactive launch: `sim_viewer/sim_web.sh --walk rl_move/sim/policies/<name
above>`; headless HTTP capture (09-10, `web_session_drivecapture.py`, fixed
same day to resend the drive heartbeat like the real browser does) now
PASSES with real translation: `stalled_phases: []`, 0 falls, 0 rejected
commands, per-phase `vx_body`/`vy_body` direction-correct and nonzero
through forward/crab-right/diag-left/reverse/restart
(`logs/manual_drive/rlonly_champion_websession_capture_09-10_heartbeatfix/`,
`CURRENT_TRUTHS.md` 09-10 root-cause entry). Known
limits: a SUSTAINED (~15s) off-forward heading chronically sacrifices one
front leg's swing (15 repair mechanisms CLOSED FAIL as of 09-13 incl. the
entire named RND family — full-obs/heading-gated/per-leg-obs-masked — and
the joystick track's own cert-gated heading-widening curriculum, whose
recalibrated V10 variant fixed its own stuck-bucket-0 defect but then
regressed on-axis gait (new falls) instead — `walkcurr/STATUS.md` 09-13;
no named lever remains, needs a fresh design note);
joystick DONE-gate FAILS on slip (>3x band) — neither blocks the
non-interactive deliverable above. **UPDATE 09-10/09-11 (op_20260910_50hz):**
the deployable candidate is now `bundle_rlonly_v2` (v1's 100 Hz export trips
the hexapod2 MCU-bridge timing fault, superseded) — a 100->50Hz warm-start
transfer of this same clean-lineage champion, matched-parent-verified per
seed; all n=3/3 seeds (s0/s1/s2) now PASSED their +18M acquisition
continuation and are exported (`walkscratch_rlonly_widen8_crutchoff_{s0,s1,
s2}_warmadapt_50hz_acq1.json`), completing the seed triplet. Same known
limits carried forward unchanged (off-axis-heading front-pair sacrifice,
broken rise/hold/lower — walk-role only). Transfer manifest + registered
bounded-trial plan at `walkcurr/bundle_rlonly_v2/`. **UPDATE 09-17
(lifecycle composition):** a separately-trained clean-RL rise+hold role
(`bundle_rlonly_stance_v1`, PASS 12/12 hold + 12/12 rise-flat, flat-start
only) now hands off DIRECTLY (no scripted blend) to this walk role with
0/12 falls (6 det + 6 stochastic sim episodes) and drive quality matching
the walk role's own clean-reset control band — first time any `rl_only`
composition beyond the single walk role has been built and evidenced.
`lower` is still CLOSED (16/16 agent-doable mechanism classes refuted,
parked on Robot Lab achievability review) so this is rise+hold+walk, not a
full sit-to-walk-to-sit cycle, and it is sim-only (no physical motion): a
physical trial additionally needs Robot Lab to build a runtime that
switches each role's own motor/safety contract at the handoff tick.
Transfer manifest: `walkcurr/bundle_rlonly_lifecycle_v1/`.

## Recorded method milestones — not parent-goal completion

- `joystick`: GREEN 08-23 at the legacy 60 s randomized MuJoCo gate
  (`stotight45-seed13`, zero falls); physical drive goes through Robot Lab.
- `amp`: GREEN 08-23 at sim-transfer M5 (`phasehz11_s29`, demonstration-
  assisted); hardware M6 goes through Robot Lab under Goal 1.
- `cpg`: GREEN 08-23 at the contextual walk/turn/stop gate (adoption candidate).
- `walkcurr`: sim-demo candidate above (09-09); easy-sim acquisition is an
  intermediate Goal-2 milestone (journal/`CURRENT_TRUTHS.md`).
- `standwalk`: single-policy method stays separate from controller
  composition — check its journal before proposing a new lever.
- `assistfade`: rungs 1-4 + residual-anneal-gate (~36 arms) now ALL closed —
  every "fade assist to full raw authority" mechanism fails on mesh/100Hz.
  Persistent BC-anchor rung 0 stays production-usable; assisted ancestry
  cannot qualify for Goal 2.
- `todaypolicy`: the 08-30 bundle packaging is a milestone; `env_yawpri`
  gained yaw at a 55% cost, shared/fixed-duty variants refuted (delivery journal).

Registry: `rl_move/orchestrator/tracks.json`. Method evidence and queues:
`rl_docs/tracks/<track>/STATUS.md`. No closed recipe is reopened by this
reorganization; there is no requirement to make every method green.

## Ownership and actual waits

Cloud cycles prepare sim evidence and controller handoffs; Robot Lab owns
serialized physical experiments under standing authority and live camera/
telemetry/abort rules. Routine calibration/bounded motion/deployment are
not blanket operator blockers; only hands-on needs or spend/capacity
increases beyond guardrails are operator waits.

WAITING-ON (refreshed 2026-09-20 meta; speed track UNPARKED — new
hardware evidence via main 94f33b076/98136faa1, see `speed/STATUS.md`
Next item 4; blocker blk_7072945137ee resolved):
- `[operator]` raw PS200 per-joint telemetry export still wanted (the
  09-20 commits landed the fitted current model + divergence summary,
  not the raw traces); no longer the sole research lever.
- `[Robot Lab]` speed track's own agent-doable roll-signature mechanism
  inventory is now fully exhausted (09-20, same day): DESIGN.md's
  named families (mass/CoM/inertia, friction, contact compliance,
  actuator strength/gain/damping/slew/current, latency/dropout,
  encoder backlash/deadband, IMU bias/mount, link length, per-leg
  asymmetry) plus chassis/mount flex, foot contact softness, foot
  torsional friction and now a transient gait-phase-coupled foot-catch
  event are ALL closed FAIL/NULL — either no dose-response at all, or
  (foot-catch) a real dose-response that is not PS200-selective and
  only reaches hardware scale by breaking DESIGN.md's own speed/
  wrong-way gate. See `speed/STATUS.md` 09-20 ~11:0x. No further
  cloud-originated speed-track roll-mechanism arm is justified until
  Robot Lab's own physical instrumentation (second IMU/AprilTag,
  photographed deflection, foot force sensing) or a genuinely new
  structural idea appears.
- `[Robot Lab]` bounded physical joystick trials of the two GO bundles:
  `todaypolicy-50hz-v1` (any_means) and `walkcurr/bundle_rlonly_v2`
  (rl_only) — transfer manifests and trial plans already packaged.
- `[Robot Lab]` `standwalk`'s deployable-width transformer grid is
  sim-complete — `tf64l2h16` (2-layer/16-frame, ~5ms/act projected)
  6/6 PASS (base+ceil15+ceil20, 2 seeds) and `tf128l2h16` (~9ms/act
  projected) 7/7 PASS (base+ceil15+ceil20x2seeds+ceil20-stepping-stone)
  at the operator's per-leg-asymmetric DR ceilings, all exported
  (`linux_control/policies/adapt50hz_tf{64,128}l2h16_noramp_ceil{15,20}_
  *.json`, parity ~1.2-1.8e-7). One thing still missing before a
  bounded trial, genuinely physical: the ~5/~9ms per-act figures are a
  same-runtime-shape PROJECTION (measured on other widths on
  hexapod2's PR#10 numpy runtime), NOT yet measured on these exact
  exported weights — measure first. **UPDATE 2026-09-26 ~14:0x:** the
  other named gap (the randomized 60s joystick DONE-gate) was
  mis-tagged `[Robot Lab]` — it is pure CPU MuJoCo simulation, not a
  physical dependency; a cloud refill cycle launched it this cycle for
  the 4 ceil20 PASS checkpoints (both seeds x both widths), detached on
  each run's own idle pod, registered via `evalpending` — read next
  cycle (`standwalk/STATUS.md` 2026-09-26 ~14:0x). No transfer manifest
  packaged yet; `ops.sh index promising --track standwalk` lists every
  exported checkpoint. Recommend tf64l2h16 first (fastest, DR-robust
  through ceil20 on both seeds).
- `[Robot Lab]` achievability review for `walkcurr`'s `lower` role
  (controlled RL descent to <20mm terminal height error): 16/16
  agent-doable mechanism classes now closed FAIL (reward pricing,
  curriculum, observation space x2, multi-task inheritance,
  architecture/GRU — full list `walkcurr/STATUS.md`/`CURRENT_TRUTHS.md`
  09-17), all converging on the same ~20-45mm partial-descend-then-
  freeze absorbing state. Question: is a controlled vertical lower
  physically achievable at all given this robot's actuator/gearing/
  mass budget, independent of RL recipe? No further cloud-originated
  `lower` RL arm is justified until this lands or a genuinely new
  structural idea appears.
- `[operator]` scope ruling for `walkcurr`'s `walkyaw` turn-in-place
  freeze (updated 2026-09-18 ~03:1x): 27/27 agent-doable mechanism
  classes closed FAIL-MECHANISM (reward pricing, action gating, DC
  action bias, exposure/init/warm-start, observation space, gSDE at two
  cadences, recurrent GRU, RSI-init, turn-magnitude curriculum,
  per-leg Cartesian foot-target IK — full chain in `walkcurr/
  STATUS.md`/`CURRENT_TRUTHS.md` 09-18). Scripted tripod on the exact
  training cfg turns at ±0.098 rad/s, so the motion is mechanically
  achievable; RL never finds it across any tried lever. Candidate (b)
  (global body-twist IK) is now RESOLVED without operator input: it is
  `rl_only`-ILLEGAL by the campaign's own existing gait-clock contract
  (the IK map needs a live stance/swing assignment to be well-formed,
  which is itself gait structure) — closed by applying written policy,
  not a new ruling. Only (d), accepting the walkyaw envelope gap
  (reverses the operator's own 09-13 full-envelope order), remains
  genuinely open — a scope reversal, not a design choice, so it is not
  assume-and-go-able. With `lower`, this is the one remaining Goal-2
  full-envelope gap parked on an explicit ruling; no further
  cloud-originated single-lever walkyaw arm is justified without one.

## Doc rules

Keep under 100 lines. Replace stale status; put history in `RL_LOG.md` and
generated run docs. Do not infer current fleet activity from this digest.
