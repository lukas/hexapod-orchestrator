# RL Plan — two goals

Reset by the operator 2026-08-21. This file is the current operating
plan; history belongs in `archive/`, `RL_LOG.md`, and generated run
docs. Keep this file under 150 lines.

## The two goals (the only agent-driven work)

1. **`joystick`** — RL from the simple programmatic gait to real
   joystick control. DONE: 60 s randomized joystick script in MuJoCo,
   zero falls, directions followed, slip/m within the teacher band
   (<=~2.9); n>=12 det+sto, DR-0 + own-DR, held-out commands.
   Track doc: `rl_docs/tracks/joystick/STATUS.md`.
2. **`amp`** — the from-scratch AMP program per
   `rl_docs/AMP_LOCOMOTION.md` (no Isaac Lab; MJX stack; build all
   needed tools; never pause on operator input). DONE: milestone M5
   (MuJoCo cross-engine transfer). M6 hardware is operator-owned.
   Track doc: `rl_docs/tracks/amp/STATUS.md`.

The loop does not stop until both gates are green. The operator may
kick off out-of-scope runs; they are triaged honestly but spawn no
agent follow-ups.

## Startup packet

1. `CURRENT_TRUTHS.md` — accepted facts; wins on conflict
2. this file
3. the relevant `rl_docs/tracks/<track>/STATUS.md`
4. `RESEARCH_RULES.md` + `RUN_INTERPRETATION_RULES.md` before
   launch/triage
5. `rl_docs/COMMANDS.md` for helpers

## Binding rulings

- **08-21 interpretation ruling:** bad evals + rising reward = go
  longer and/or align the reward with the evals; never a reflex FAIL
  (`RUN_INTERPRETATION_RULES.md`).
- **No operator pauses:** assume-and-go with recorded assumptions;
  only physical-robot access and spend wait.
- **Build the tools:** missing harnesses/banks/models are cycle work,
  written, tested, and snapshotted before training on them.

## Active queue

### joystick — next arms

1. [SPECIFICATION] Build the 60 s joystick gate harness: randomized
   held-out command scripts (speeds, headings incl. rear, turns,
   stops, reverses), 60 s horizon, metrics = falls, heading obedience
   (delta vs teacher-clone floor), slip/m, per-leg gait validity,
   video. Plus a WALK/JOYSTICK semantics bank proving the training
   reward ranks gate behavior above park/paddle/overspeed/
   sacrificed-leg.
2. [DISCOVERY→ACQUISITION] RL fine-tune from the phase-conditioned BC
   clone `ppo_goal_cw_bcgait_init_fullprof_phase1` with the aligned
   reward; a walk-champion-lineage arm as control. Continue while
   reward and gate metrics rise together.
3. [HARDENING] Widen command envelope; DR to own-DR zero-fall; then
   run the DONE gate panel.

### amp — next arms (brief §17)

1. [SPECIFICATION/CODE] M0: joystick-command env on MJX with
   actor/critic obs split; GRU/history actor + deterministic
   recurrent eval; fault-injection + push hooks.
2. [SPECIFICATION/CODE] M1: motion library from the scripted teacher
   (all command families + mirroring/speed/phase augmentation) with
   validation metrics; AMP discriminator + replay + style reward.
3. [CANARY] Smoke: PPO gradients flow, discriminator trains without
   instant saturation.
4. [ACQUISITION] Wave 1 on 8 pods: 3 seeds at task/style 0.5/0.5,
   no-AMP ablation, recurrent vs fixed-history, ±AMP weight. Select
   on videos + tracking/stability.

## Inherited assets (both tracks)

- Scripted tripod teacher verified clean at the measured tibia-150
  plant (0.06–0.10 m/s × 4 headings, zero falls, slip/m 1.4–2.9, full
  fast profile) — the joystick starting point and the amp motion-prior
  seed.
- Phase-conditioned BC clone passes the direction-first curriculum
  with zero RL (see joystick track doc).
- Download hierarchy baseline (`footlow2_hard1` + `bcgait1_hard1` +
  session controller; det 0.967 / sto 0.853, n=600) — the fallback
  deployable answer in `rl_docs/DOWNLOAD_ANSWER.md`.
- MJX/Warp GPU stack: 12 H200 pods, ~4096 envs each, model DR,
  canaries, eval/video, desync. Asym-critic flag exists.

## Operator-owned items (parked, do not block the tracks)

- Physical robot: bench promotion, calibration readings, any motion.
- Spend/capacity changes beyond guardrails.
- Out-of-scope runs (recover mode, quad tricks, etc.) — operator
  kicks only.

## Documentation discipline

Replace stale narrative with current state. Budgets: `STATUS.md`
<=100 lines, track STATUS <=120, this file <=150,
`CURRENT_TRUTHS.md` <=80. One RL_LOG line per cycle via
`ops.sh logline`. Long audits go to `archive/`.
