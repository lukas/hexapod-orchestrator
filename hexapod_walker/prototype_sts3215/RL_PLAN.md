# STS3215 Hexapod — RL Phase 1 Plan
## Stationary Balance, Target Tracking, and Safe Real-Robot RL

**Status:** Approved merged plan (original + GPT feedback + sim/real brief)  
**Date:** 2026-08-06 (updated 2026-08-07)  
**Robot:** `prototype_sts3215` — 18× STS3215, Uno Q, MPU-6050  
**Package:** `rl_move/`

This is the **single** RL plan document (`RL_PLAN_GPT_FEEDBACK.md` and
`../RL_LEARNING_BRIEF.md` were merged in and deleted). Sim↔real facts from
the learning brief live in **Appendix A**. Related code:
[`../sts/`](../sts/) (residual **walk** RL — do not hijack).

---

## 0. Status log

**2026-08-07 (short + rebuild):** robot had an electrical short; user
rebuilt it. Board recovered; `web_drive.py` on the robot was corrupted
(SyntaxError crash-loop) and was redeployed from the repo. L0 knee servo
was physically replaced and re-ID'd factory 1 → **4**. **All 18 servos
(IDs 2–19) answer**, ~12.2 V, cool, no alarms. Δq stand-guard raised
**25° → 90°** (operator approved) so sit→stand (~80° knee swing) is not
refused; `MAX_SAFE_DELTA_DEG` in `linux_control/drive_controller.py`.

**Where we are in the plan:** Phase 0 (basic controls). Zeros were
remapped via `set_zero` before the short; **re-verify zeros after the
rebuild** before trusting absolute poses. The motor-dynamics probe
(`linux_control/motor_dynamics.py`, `POST /api/rl/probe_dynamics`) — the
"collect real-world sys-ID data to calibrate MuJoCo" step — browned out
the board on its first run (full-body SyncWrite bug); it was rewritten to
move one joint at a time with soft torque + 0.9 A trip. On 2026-08-07 it
was extended into the trimmed battery (§1 step 0.5): full battery on 3
representative joints + verify pass on the rest, smoke-tested against a
simulated bus. **Ran successfully on hardware 2026-08-07** — see the
calibration entry below.

**Sys-ID start pose (2026-08-07 operator decision):** all tests run from
**sit zero** — operator puts the robot at 0° with legs spread straight
out, resting on the bench, then `set_zero`. **No captured plant, no
standing pose is needed or allowed for the sys-ID phase.** Plant/stance
only enters at the balance milestone (§1 step 1), and even then as an
operator-posed snapshot, not a computed pose.

**2026-08-07 (sim training stack built):** the MuJoCo half of the plan
now exists — `rl_move/sim/` (see §17): fit script (motor_model.json →
simulate-and-match kp/kv/frictionloss + copied latency / velocity ceiling
/ deadband), a sim twin of `HexapodBalanceEnv` with identical obs / action
/ reward / safety code and a `ServoProfile` actuation model, per-episode
domain randomization, a replay-compare gate, and an SB3 PPO harness.
Smoke-tested end-to-end (zero-action stand holds; PPO trains at
~1000 fps; replay-compare correctly FAILs on deliberately mismatched
latency). Currently running on **default** (unfitted) params — the
hardware battery still needs its first successful run to calibrate it.

**2026-08-07 (sim scaffolding built):** the MuJoCo training half now
exists under `rl_move/sim/` (§5.1) — fit script, sim twin env with
servo latency/profile/deadband emulation, domain randomization,
replay-compare gate, PPO harness. Pipeline smoke-tested end-to-end with
default params (PPO ~1000 fps on the laptop). It is idle until the
hardware battery produces a real `motor_model.json`; then:
`fit_motor_model` → `replay_compare` (must PASS) → `train_ppo_sim`.

**2026-08-07 (battery ran; sim CALIBRATED, replay gate PASSES):** the
trimmed dynamics battery ran clean on hardware from sit zero — 18/18
joints, ~100 s, no overcurrent, robot limped after. Before the run,
`bench_api.py` + `motor_dynamics.py` on the robot were found null-byte
corrupted (same failure mode as `web_drive.py` after the short) and were
redeployed with checksum verification. Findings baked into the sim:

- **Latency is large: ~150–200 ms** command→10%-of-step (delay), joint
  spread 147–226 ms (L0/L3 hips slowest). At 25 Hz that is 4–5 ticks.
- **The STS speed feedback was misdecoded 50×, not garbage** (resolved
  2026-08-07 after a GPT hint): the bus layers used the SCS-series
  0.732 rpm/unit convention, but the STS3215 present-speed unit is
  counts/s (× 360/4096). The "1537 °/s" readings were exactly the
  commanded 350 counts/s. Decode fixed in `mcu_feetech_bus.py` +
  `urt2_setup/feetech_bus.py`; `_fit_step` keeps position-derived speed
  (robust, and old CSVs stay interpretable), and `fit_motor_model`
  recomputes targets from the raw battery CSV.
- **The acceleration ramp matters**: ACC=15 ≈ 132 °/s² takes ~0.23 s to
  reach cruise. `ServoProfile` is now a trapezoid (accel-limited), and
  `latency_ms` is *fitted* against delay (a direct copy double-counts
  profile travel time — the replay gate caught exactly this).
- Deadband 0.35–0.49°, zero overshoot, tracking 97.5–99.6%.

Replay-compare after refit: rise bias −3 ms, settle bias −24 ms,
overshoot exact, delay bias −1.3 ms (per-joint scatter is absorbed by
the DR latency scale, and the gate now distinguishes unbiased scatter
from miscalibration). **PASS — sim training on the calibrated
`sim_model.json` is unblocked.**

**2026-08-07 (first PPO runs + env fixes + goal-conditioned task):** the
first calibrated 200k-step balance run exposed three env bugs, all fixed:

- **Over-current tripped on a single sample.** DR placement noise +
  stiff fitted kp + pinned feet = isometric leg fights (the 2026-08-06
  stilt-fight mode, faithfully reproduced) that killed episodes on step 1
  before the policy could react. The trip now requires **sustained**
  over-current (`safety.over_current_trip_s`, 0.8 s); the sim current
  estimate is low-passed ~0.1 s (hardware reads current at ~10 Hz). The
  per-tick effort penalty is unchanged, so unloading is still rewarded.
- **Near-rigid foot contacts concentrated all load on 2-3 legs**
  (three-legged-stool under mm-scale geometry DR) → 2-3 A "quiet" stands.
  Foot solref softened 3× (rubber feet + PLA flex), and resets settle
  with slippery feet first (a human placement micro-slips/relaxes).
  Quiet stands now hold 0.5-0.8 A; only deliberate bad starts fight.
- **Tilt guard used absolute measured tilt**, so IMU mount bias ate the
  whole ±10° budget. It now trips on tilt **change from the episode-start
  reference** (`SafetyLayer.set_tilt_reference`, wired into both envs) —
  a biased IMU still measures tipping correctly as a delta.

New: **goal-conditioned lean / track / weight-shift task** (§17,
`sim/goal_task.py`, default for `train_ppo_sim --task goal`): per-episode
goal (hold / constant lean / slow moving roll-pitch reference / unload
leg k) appended to obs (46+8 dims), reward tracks the reference and
drives the unload leg's currents to zero. Chosen because a "hold still"
policy barely excites the IMU; deliberate leans exercise the whole
latency/load pipeline safely (all six feet stay planted). IMU DR
extended for "the IMU could be installed anywhere": mount **position**
randomized (±70 mm xy, −20…+100 mm z) with lever-arm acceleration
modeled at the point, residual mount rotation widened 3° → 10°, and the
sim now runs the same complementary attitude filter as the hardware
estimator (raw accel tilt would see ±20° single-tick lever-arm spikes
that real firmware filters out).

---

## 1. Goal

**Not locomotion. Not “make it stand” as the first problem.**

Order of work (hard):

0. **Basic controls** — correct zeros, every servo on the bus, single-joint
   and small multi-joint air moves, predict↔encoder match, limp/E-stop,
   soft torque, current/temp visible. Fix dead IDs (e.g. L5 knee) first.
0.5. **Motor sys-ID** — from sit zero (legs straight out on the bench, no
   plant), run the trimmed dynamics battery in air (~10 min total):
   - **Full battery** on one yaw + one hip + one knee (default L2,
     joints 6/7/8): steps ±3° and ±12° × 2 repeats at the loop's fixed
     speed/acc profile, plus a slow ±6° triangle ramp.
   - **Verify pass** on the other 15 joints: single ±12° step pair,
     auto-checked against the axis model (deviants get flagged for a
     full run).
   - Every measurement maps to a MuJoCo knob: delay → action latency;
     rise/settle → kp/kv; peak speed → velocity ceiling; ramp →
     frictionloss/deadband; ±step current asymmetry → gravity/mass check.
   - Deliberately cut (info we would not use): speed/acc sweeps (the RL
     loop uses one fixed profile), chirps (replay-compare steps in sim
     first), separate loaded tests (± asymmetry gives it free).
   Output: `logs/motor_model.json` (per-joint + per-axis) + CSV traces
   → fit → regenerate MuJoCo XML → replay-compare (Appendix A.4).
1. **Only then** stance and hold — operator poses the robot by hand and
   snapshots it; no computed stand, no plant work before this point.
2. Then 25 Hz loop → body IK → ±1° sine → PD → tracking. **No PPO until
   those pass.** No autonomous stand-up.

Standing/balance was over-weighted in early bring-up and burned a motor.
Do not resume plant/stand work until Phase 0 basics are boringly solid.

Milestone “RL infra” (after Phase 0): hold-current → obs → fixed-foot IK →
safety → logs → zero-action + ±1° sine → scripted PD → small target
tracking.

---

## 2. Non-goals (Phase 1)

Walking / gait residuals · unconstrained 18‑D joint actions · AprilTags in
the loop · soft-torque register writes by default · millions of unsafe
exploratory steps · hijacking `../sts/StsWalkerEnv`.

---

## 3. Hardware facts

| Item | Value |
|---|---|
| DOF / IDs | 18; servos **2…19**; `joint = leg*3 + axis` |
| Links | coxa 12.5 / femur 90 / tibia 128 mm; chassis F2F **200** mm |
| **Plant** | **Captured 18-joint snapshot** (`capture_plant` → `plant_pose.json` with `joints_deg`). Default +20°/+80° is the knee **limit**, not a real stand — do not auto-blend to it. |
| Limits | yaw ±35°, hip −80…+30°, knee −20…+80° |
| Host↔MCU | `/dev/ttyHS1` @ **921600** (fallback 115200) |
| Bulk pos ×18 | ~197 Hz · Full FB ×18 ~77 Hz |
| Env rate | **Target 50 Hz**; **HW today ~25 Hz** (`config` default) — see §8 |
| Live walk | `DriveController` **20 Hz open-loop** — not the RL loop |

Prefer **HTTP** (`rl_move/API.md`, `python3 -m rl_move.remote`) over
SSH. **Do not** auto `find_plant` / stand blends (disabled without `force`
after 2026-08-06 incident). Capture plant only after operator-approved
stance + `set_zero` when needed.

### Hardware incident 2026-08-06 (mandatory)

- Logical zeros were wrong: straight-out legs already read knee ≈ −80°.
- Agents commanded stand/plant/centre in software degrees → stilts, tip,
  brownouts, ~7 A holds, **cooked L5 knee (ID 19 offline)**.
- **Rules:** set-zero-here before absolute poses; no unsupervised stand-up;
  refuse Δq > 90° without FORCE (raised from 25° on 2026-08-07, operator approved,
  so sit→stand passes); stop on missing/hot servo; HTTP not SSH
  for motion. See `.cursor/rules/hexapod-sts-hardware-safety.mdc`.

---

## 4. Reuse map

| Need | Code |
|---|---|
| Bus + IMU | `linux_control/mcu_feetech_bus.py` — `read_all_positions`, `read_all_feedback`, `read_imu`, `write_all`, `open_feetech_bus` |
| Stand | `feetech_bus.standing_pose_degrees`, `load_plant_pose` |
| Leg IK | `tripod_gait._leg_ik` |
| Limits | `AXIS_LIMITS_DEG`, `deg_to_count` |
| Stall ideas | `../sts/stall_guard.py` |
| IMU calib | `imu_calibrate.py` → `logs/imu_calib.json` |
| Log patterns | `motion_telemetry.py`, `event_log.py` |

---

## 5. Package layout

```text
prototype_sts3215/rl_move/
  config.yaml
  robot_state.py      # RobotState + estimator + qd filter
  attitude.py         # roll/pitch; persistent level from calib
  control_loop.py     # absolute-deadline 50 Hz
  body_ik.py          # FK + fixed-foot body → 18 joints
  safety.py
  logger.py           # async episode log
  env.py              # HexapodBalanceEnv
  scripted_pd.py
  scripts/
    probe_state.py    # Step B timing
    balance_test.py
    balance_sine.py
    balance_perturb.py
    balance_pd.py
    train_ppo.py      # HARDWARE PPO — only after Milestone 2
  sim/                # MuJoCo twin + training (no hardware needed) — §17
    servo_model.py    # fitted params + ServoProfile (latency/speed/deadband)
    fit_motor_model.py# motor_model.json → sim_model.json (simulate-and-match)
    sim_env.py        # SimHexapodBalanceEnv — same obs/action/reward
    domain_rand.py    # per-episode DR, ranges from measured spread
    replay_compare.py # hardware CSV vs calibrated sim — gate before PPO
    train_ppo_sim.py  # SB3 PPO harness (sim only)
  tests/
    test_body_ik.py   # FK↔IK consistency (no hardware)
```

---

## 6. Architecture

```text
Servo / IMU / clock → RobotStateEstimator → Env / PD / Policy
                            │                      │
                         Logger              SafeActionLayer
                                                   │
                                          Fixed-foot body IK
                                                   │
                                            SyncWrite servos
```

One state collector; policy never touches the bus; safety after action /
before write; NaN-safe.

---

## 7. RobotState

Units: joints rad / rad·s⁻¹; IMU rad; gyro rad·s⁻¹; accel m·s⁻²;
`time.monotonic()`.

```python
@dataclass
class RobotState:
    timestamp: float
    joint_position: np.ndarray   # (18,)
    joint_velocity: np.ndarray   # (18,) filtered
    imu_roll: float
    imu_pitch: float
    imu_yaw: float               # logged; unused by Phase-1 policy
    imu_gyro: np.ndarray         # (3,)
    imu_accel: np.ndarray        # (3,)
    commanded_position: np.ndarray
    servo_load / current / temperature: optional (18,)
    bus_ok: bool
    imu_ok: bool
    dt: float
```

**Velocity:** `qd = α·(q−q_prev)/dt + (1−α)·qd_prev`, default `α=0.3`;
reject bad `dt` / jumps; hold previous on reject.

**Attitude:** complementary/Mahony on accel+gyro. **Persistent level** from
`imu_calib.json` — episode reset must **not** redefine tilted start as
zero. No magnetometer → yaw unused in policy.

**Sensing schedule:** positions + IMU every control tick; full FB
(load/I/temp) at **~10 Hz** opportunistic — do not stall the primary
loop on full FB.

---

## 8. Timing

Absolute deadlines (`t_next += period`); log `actual_dt`, sensor /
controller / IK / command latency, overruns.

**Measured (2026-08-06):** a full tick (SyncWrite + positions + IMU,
sometimes FB) often takes **>~20 ms**, so a 50 Hz deadline overruns
almost every step. Operational default is **`control.hz: 25`**
(`dt = 0.040 s`) until the tick is slimmed. Bus headroom still exists
(pos-only ~197 Hz); the bottleneck is **Linux tick work**, not the
UART ceiling. Train / evaluate at the rate you can actually hold — do
not pretend 50 Hz if the robot ran at 25.

---

## 9. Fixed-foot body IK (main new kinematics)

At reset: FK six feet in world → freeze.  
Each step: body ⊕ (roll, pitch, height, x, y) → transform each foot into
leg frame → `_leg_ik` → yaw/hip/knee. Yaw joints **participate** in XY
shifts. Any IK failure → reject / hold last safe / terminate + log.

**Mandatory software FK↔IK tests** (±1° / ±2 mm) before hardware motion.

---

## 10. Action / observation

Action `[-1,1]^5` → roll±3°, pitch±3°, h±5 mm, x±5 mm, y±5 mm (config).

Obs (46): `(q−q_nom)₁₈`, `qd₁₈`, roll, pitch, gyro₃, prev_action₅.  
Normalize via config scales. Log accel always; optional later in obs.

Target tracking (Milestone 2+) adds target/error dims — do not train
tracking without exposing the target to the policy.

---

## 11. Reward

```text
r = -k_roll·e_roll² -k_pitch·e_pitch² -k_gyro·‖ω‖²
    -k_act·‖a‖² -k_Δact·‖a−a_prev‖² -k_current·Σi²  [- termination_penalty]
```

`alive: 0` initially (fixed-horizon). Log every component. For tracking,
errors are vs **target**, not absolute zero.

`k_current` (2026-08-07): effort penalty on Σ(servo current)² — the
"don't cook motors" signal. Hardware feeds it from the ~10 Hz full
feedback; the sim twin from actuator torque (≈1.2 A/N·m), which also
arms the SafetyLayer over-current trip in sim so stall-fighting
terminates episodes there too.

---

## 12. Episodes & safety

5 s / 250 steps. Reset: smooth stand → settle → health check → clear
transients (**not** level) → log → run.

Safety (independent): joint limits, max Δq/step, body clamps, tilt kill
(~15°), IMU stale, servo health (slow FB), NaN/Inf actions, estop →
`safe_stop` / disarm, no auto-restart.

Soft torque limit: **opt-in, default off** until register semantics verified.

---

## 13. Tests before PPO

| Order | Script | Pass criteria |
|---|---|---|
| 1 | `balance_test` | `action=0`, minutes of quiet stand, finite obs, timing logged |
| 2 | `balance_sine` | ±1° roll then pitch, correct signs/IMU |
| 3 | `balance_perturb` | log human nudge settle (no learning) |
| 4 | `balance_pd` | PD beats zero-action on gentle disturb |
| 5 | target tracking scripted | small random targets |
| 6 | PPO | only then |

---

## 14. Implementation order

| Step | Deliverable |
|---|---|
| A | Repo map (done) |
| **B** | `RobotStateEstimator` + timing probe on hardware |
| C | 50 Hz scheduler |
| D | Async logger |
| E | Body IK + FK↔IK unit tests → hardware ±1° |
| F | Safety |
| G | `balance_test` |
| H | `balance_sine` |
| I | Scripted PD |
| J | `HexapodBalanceEnv` |
| K | Randomized target tracking |
| L | PPO |

---

## 15. Coding principles

Reuse bus/IK/limits · monotonic time · fail safe · log overruns · no silent
sensor resurrection · no firmware/CAD side quests · no PPO before G–I.

---

## 16. Config sketch (`rl_move/config.yaml`)

See checked-in `config.yaml`. Key defaults: **25 Hz** (50 Hz target once
tick ≤20 ms), 5 s episodes, action limits above, `full_feedback_hz: 10`,
`enable_soft_torque_limit: false`, `reward.alive: 0`, PD gains filled
during hardware tune.

---

## 17. Sim training stack (`rl_move/sim/`)

The MuJoCo half of the plan. Everything runs on the workstation venv
(`weird_objects/.venv`: mujoco 2.3.7, stable-baselines3, torch) — the
robot is never touched.

**Pipeline** (from `prototype_sts3215/`, all `../../.venv/bin/python`):

```sh
# 1. Fit sim actuator params from the hardware battery output
python -m rl_move.sim.fit_motor_model            # reads linux_control/logs/motor_model.json
# 2. Gate: replay the battery CSV in sim, compare metrics
python -m rl_move.sim.replay_compare --csv linux_control/logs/motor_dyn_*.csv --plot
# 3. Train (DR on by default; --task goal is the default task)
python -m rl_move.sim.train_ppo_sim --steps 2000000 --n-envs 8
# plain hold-level task: --task balance ; smoke check any time: --smoke
```

**Tasks** (`--task`):

- `goal` (default) — goal-conditioned lean / track / weight-shift
  (`sim/goal_task.py`). Per episode one of: *hold* (zero refs), *lean*
  (constant roll/pitch target, ramped in), *track* (slow moving
  roll/pitch reference — sums of 2.5–8 s sines), *unload leg k* (shift
  weight until that leg's currents ≈ 0). The 8-dim goal (scaled refs +
  leg one-hot) is appended to the obs (46 → 54); reward tracks the
  reference instead of zero and adds `k_unload · mean|I_leg|`. All six
  feet stay planted for every goal — this is the safest task that still
  deliberately excites the IMU and the latency/load pipeline.
- `balance` — the original hold-level task (46-dim obs), kept as the
  zero-goal special case / regression baseline.

How the sim stays honest:

- **Same code, not similar code:** the sim env imports the hardware
  env's `build_obs` / `compute_reward`, the same `FixedFootBodyIK`, and
  the same `SafetyLayer` (tilt kill, Δq rate limit, joint limits).
- **Hardware-like actuation:** joints are driven through `ServoProfile`
  — measured command latency, the servo's internal profile-speed slew
  (~31 °/s at speed 350), and deadband — not ideal position control.
  The fit script drives the *same class*, so fitted params transfer.
- **Fit anchors:** delay → latency (copied), peak speed → velocity
  ceiling (copied), ramp → deadband (copied); kp / kv / frictionloss
  fitted by replaying the ±12° bench steps in sim and matching
  rise / settle / overshoot / **tracking_pct** (steady-state gravity sag —
  the only metric that pins stiffness, since rise time is
  profile-speed-limited).
- **Replay-compare is the gate:** if sim step responses don't match the
  hardware CSV within tolerance (delay 30 ms, rise 40 ms, settle 80 ms,
  overshoot 1°), fix the fit before believing any trained policy.
- **Domain randomization** (per episode):
  - *Geometry:* leg link lengths — global ±2% (print/CAD error) ×
    per-leg per-segment ±1.2% (assembly) — mutated on the loaded model
    while the policy-side IK keeps **nominal** lengths; per-link mass
    jitter ±10%.
  - *Body:* chassis mass ±20% / CoM ±12 mm (A.4's known mass
    uncertainty).
  - *World:* ground friction 0.6–1.4×, contact compliance 0.7–2×,
    ground slope up to 2° (tilted gravity).
  - *Actuation:* kp/kv spread (widened by the measured joint-to-joint
    spread in `sim_model.json`), torque/voltage 0.8–1.05×, latency
    0.7–1.8×, deadband, velocity ceiling, dropped SyncWrites (≤5%/tick).
  - *Sensing:* **joint zero bias ±1°** (the 2026-08-06 failure mode),
    encoder noise, **IMU mount rotation ±10°/axis** (residual after
    `imu_calibrate`; applied to both tilt and gyro axes), **IMU mount
    position ±70 mm xy / −20…+100 mm z** (the IMU could be bolted
    anywhere — the accelerometer is computed at the randomized point, so
    lever-arm acceleration corrupts tilt during rotation exactly like a
    corner-mounted IMU), tilt/gyro bias + noise, action noise. Tilt goes
    through the same complementary filter (α = 0.98) as the hardware
    estimator.
  - *Start pose:* per-joint hand-placement slop ±2°, and in 25% of
    episodes 1–3 joints start **way off** (8–35°, slipped zero /
    operator error). The env then does what the hardware env does —
    hold-current: nominal = the pose the robot actually settled at, feet
    frozen where they really are — so the policy learns to level the
    body from degraded stances. Combined with the `k_current` effort
    penalty + in-sim over-current termination (§11), "fight a bad pose"
    is a strictly losing strategy. (Note: the hardware env's
    `max_plant_delta_deg: 15` refuses starts this bad on the real robot;
    the sim trains past that guard on purpose — robustness is free in
    sim, and the guard stays on the hardware.)

Safety semantics (shared `SafetyLayer`, both envs): tilt trips on the
**change from the episode-start reference** (mount bias / slope isn't
"tipping"); over-current trips only when **sustained**
(`over_current_trip_s`, 0.8 s) — the effort penalty punishes every
over-current tick, the trip is the backstop.

Status: calibrated on the 2026-08-07 hardware battery; replay gate
PASSES. First PPO runs done (see status log). Deploying a sim policy to
the robot remains gated on Milestone 2 + operator request.

---

## Appendix A — Sim ↔ real facts (merged from RL_LEARNING_BRIEF)

Key facts for anyone doing MuJoCo / transfer work. Verified 2026-08-06.

### A.1 Stand plant mismatch (the #1 sim↔real gap)

| Context | Hip | Knee | Approx foot drop |
|---|---|---|---|
| **Live robot stand / plant** (default or `plant_pose.json`) | **+20°** | **+80°** | ~157–159 mm (feet under body) |
| **CAD / MuJoCo / `sts/` RL posture** | **−25°** | **+60°** | ~35 mm (feet out, crouch) |

Align plant height before training anything for transfer, or policies
trained on the crouch will fight the real stand. Positive hip = femur
toward the floor on hardware.

### A.2 Motors / bus

- STS3215, ~12 V / 30 kg·cm; half-duplex TTL @ 1 Mbps; 4096 counts/rev,
  centre 2048 (≈11.378 counts/deg).
- `WritePosEx` position + speed + acc. **speed=0 means MAX** — drivers
  coerce to hold speed 250.
- Feedback available per servo: pos, speed, load %, bus V, temp,
  current (~6.5 mA/LSB). No foot-force sensors, no external encoders.
- Soft torque limit SRAM addr 48 (0–1000).

### A.3 Rates

| Path | Rate |
|---|---|
| Robot teleop walk (`DriveController`) | 20 Hz SyncWrite, **open-loop** (no per-tick read-back) |
| RL loop target | 25 Hz today, 50 Hz once tick ≤ 20 ms |
| MuJoCo timestep | 500 Hz (0.002 s) |
| Bulk position read ×18 | ~197 Hz ceiling; full feedback ×18 ~77 Hz |

### A.4 MuJoCo model fidelity (`mujoco_prototype.py`)

- Link lengths match CAD (coxa 12.5 / femur 90 / tibia 128 mm; chassis
  hex 200 mm flat-to-flat).
- Collision = chassis box + foot spheres; meshes visual-only. Sim foot
  *touch* sensors are privileged (not on the real bus).
- Lumped mass ~2.1 kg in sim vs ~1.3 kg in CAD text — **mass is
  uncertain; weigh or identify before trusting dynamics.** This is what
  the motor-dynamics / sys-ID probe feeds.
- Actuator torque ceiling ≈ 2.70 N·m (near nameplate stall).

### A.5 Existing walk RL stack (`../sts/`) — do not hijack

Residual PPO on top of `TripodGait` (57-dim base obs + STS motor
channels; per-joint residual ≈ ±0.06 rad). Checked-in artifacts are
~4k-step smoke runs, not trained policies. It still uses the −25°/+60°
crouch and privileged contacts; treat as a separate track from
`rl_move/`.

### A.6 Doc conflicts to ignore

- Stand “−25°/+60°” in older READMEs / WIRING → superseded by
  `DEFAULT_STAND_* = +20/+80` on the robot.
- “No MCU bridge / Linux owns USB” wiring blurbs → superseded by
  `feetech_bridge` + `mcu_feetech_bus.open_feetech_bus()`.
- `sts/posture.py` comment claiming its stand matches
  `feetech_bus.standing_pose` → false today (matches MuJoCo crouch).
