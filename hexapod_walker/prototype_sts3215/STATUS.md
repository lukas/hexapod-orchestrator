# STATUS — two walking goals, each in sim and on hardware

Goal structure clarified by Lukas on 2026-09-08. This is an operator-facing
digest, not a live fleet snapshot. `RL_GOALS.md` owns purpose and priorities;
`CURRENT_TRUTHS.md` owns accepted evidence. Consult the state ledger and
track journals for current run/queue status.

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
Non-interactive reproducible sim video now exists for a candidate under each
goal (below). **UPDATE 09-10:** the interactive-control gap is now
substantially closed headlessly for both — `web_session_drivecapture.py`
drives the real browser-facing HTTP joystick API (no display needed; only
the optional native viewer window ever did) and confirms a real,
non-scripted checkpoint survives a full multi-command session with zero
falls; it also found+fixed a bug where the session ran non-default-cfg
champions under the wrong joint action-box (`CURRENT_TRUTHS.md` 09-10). A
residual translation gap is flagged, not hidden. Neither outcome is
established yet. Physical acceptance needs a named build/
controller, a bounded joystick trial with video/telemetry, and reported
direction/speed/yaw/start/stop limits; `rl_only` also needs clean training
ancestry. Next step: the best-supported candidate's measured physical
comparison through Robot Lab, after its contract/readiness checks; it does
not wait for every method.

## Recorded sim-demo candidates and limitations

**`any_means`: `todaypolicy-mlpsf-tuck-v1`**, PACKAGED 08-30, all TODAY bars
passing on a fresh controller-side full-mesh regen: scripted-or-learned tuck
stand/lower plus `cw-walk-allheading-mlp-singleframe-acq1-stdanneal`. 0
terminations, no sacrificed legs, course error median 2.42°/p90 6.98°,
progress ratio 0.418 — GO for controller handoff, not physical acceptance;
speed-soft, zero turn authority. Selector/evidence:
`rl_docs/tracks/todaypolicy/bundle_mlpsf_tuck_v1/`. The 09-05 delivery
verification flagged a model/regen mismatch — resolve from
`rl_docs/tracks/todaypolicy/hardware_delivery/STATUS.md` before transfer.

**`rl_only`: `ppo_goal_cw_walkscratch_crutchoff_s0_widen8_legdutyratio_
swinggap_dose10_plusduty_acq1_cont10m.zip`** (walkcurr, no BC/AMP/demo in
lineage), recipe-default widen8 champion, durability-confirmed at 50M steps.
Reproducible non-interactive video (09-09, `ops.sh drivevideo ... --script
human[_turn]`): forward/crab-right/diag-left/reverse/**stop**/**restart**,
0 falls, `gait_valid=true`, `sacrificed_legs=[]` for the full 26 s episode.
Interactive launch: `sim_viewer/sim_web.sh --walk rl_move/sim/policies/<name
above>`; headless HTTP capture (09-10, `web_session_drivecapture.py` +
its `--cfg-set` matching this champion's box/bias) verified zero falls
through a full driven session. Known limitations: a SUSTAINED (~15s)
off-forward heading still chronically sacrifices one front leg's swing (8
repair mechanisms CLOSED FAIL, `rl_docs/tracks/walkcurr/STATUS.md` 09-09);
the joystick DONE-gate FAILS on slip (>3x band); and the HTTP-driven
session's translation isn't yet confirmed (`CURRENT_TRUTHS.md` 09-10).
None block this sim-demo deliverable but all are honest, unfixed gaps.
Physical-handoff prep (09-09): exported to the robot's numpy runtime (built
N-layer/ELU export support) with a transfer manifest + registered bounded-
trial plan at `rl_docs/tracks/walkcurr/bundle_rlonly_v1/` (walk role only).

## Recorded method milestones — not parent-goal completion

- `joystick`: GREEN 08-23 at the legacy 60 s randomized MuJoCo gate
  (`stotight45-seed13`, zero falls); physical drive goes through Robot Lab.
- `amp`: GREEN 08-23 at simulation-transfer M5 (`phasehz11_s29` family,
  demonstration-assisted); hardware M6 goes through Robot Lab under Goal 1.
- `cpg`: GREEN 08-23 at the contextual walking/turning/stopping gate; its
  saved controller is a candidate for measured adoption comparisons.
- `walkcurr`: sim-demo candidate recorded above (09-09); easy-sim acquisition
  is an intermediate Goal-2 milestone — see its journal/`CURRENT_TRUTHS.md`.
- `standwalk`: the single-policy method remains separate from useful
  controller composition; check its journal before proposing a new lever.
- `assistfade`: rungs 1-4 + the residual-anneal-gate mechanism (~36 arms) are
  now ALL closed — every "fade assist to full raw authority" mechanism fails
  on mesh/100Hz. Persistent BC-anchor rung 0 stays production-usable;
  assisted ancestry cannot qualify for Goal 2.
- `todaypolicy`: the 08-30 bundle packaging is a milestone; `env_yawpri`
  gained yaw at a 55% cost, shared/fixed-duty variants refuted (delivery journal).

Registry: `rl_move/orchestrator/tracks.json`. Method evidence and queues:
`rl_docs/tracks/<track>/STATUS.md`. No closed recipe is reopened by this
reorganization; there is no requirement to make every method green.

## Ownership and actual waits

Cloud cycles prepare sim evidence and controller handoffs; Robot Lab owns
serialized physical experiments under standing authority and the live
camera/telemetry/abort rules. Routine calibration/bounded motion/deployment/
recovery are not blanket operator blockers; only concrete hands-on needs or
spend/capacity increases beyond guardrails are operator waits.

## Doc rules

Keep under 100 lines. Replace stale status; put history in `RL_LOG.md` and
generated run docs. Do not infer current fleet activity from this digest.
