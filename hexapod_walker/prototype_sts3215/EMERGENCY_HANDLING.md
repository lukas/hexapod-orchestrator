# Hexapod emergency handling

This is the canonical response procedure for supervised physical-robot runs.
The goal is to stop hazardous motion without creating a second hazard through
an unnecessary sit, zero, plant, or torque-off transition.

## Core rule: use the least additional motion that makes the robot safe

An observation is not automatically a confirmed fault. In particular, one
missing servo reply is common bus noise and **must not** trigger a sit or limp.
Do not turn an uncertain reading into a posture transition.

These actions are different and must not be conflated:

- **Hold**: keep the last commanded stable pose with torque enabled.
- **Controlled gait stop**: stop at a gait-neutral phase, command zero gait
  velocity, then hold the resulting pose.
- **Lower/sit/safe-zero**: commanded whole-body motion. This is not an
  emergency action and requires healthy feedback plus a known safe path.
- **Limp / `X`**: disable torque. Use this for a confirmed hard fault, an
  unstable/fighting pose, or when active motion cannot otherwise be stopped.

## Response matrix

| Observation | Confirmation | Immediate response | Resume rule |
|---|---|---|---|
| One incomplete ServoWatch scan or one missing feedback reply | Fewer than 3 consecutive scans with distinct fresh timestamps | Keep the current controller/pose, issue no new transition, keep recording, and obtain fresh scans | If 18/18 returns, log `transient_missing_servo_ignored` and continue |
| Persistent missing servo | 3 consecutive incomplete scans with distinct fresh timestamps | Confirmed hard stop: `X`; do **not** sit or safe-zero | Human inspection and explicit operator approval |
| Telemetry/API read failure | Fewer than 3 consecutive attempts | Keep the current controller/pose and retry promptly; do not sit or limp | Continue after fresh telemetry confirms health |
| Telemetry lost while motion is active | 3 consecutive failures, or state/stop cannot be verified | Best-effort `X`; no recovery motion | Human inspection and explicit operator approval |
| Camera/tag/recorder/framework failure while stationary | One confirmed software/data failure with robot telemetry still healthy | Hold the current pose; keep any surviving logs open | Inspect the live camera and fresh telemetry; retry from the last safe checkpoint if both are normal |
| Camera/tag/recorder/framework failure while walking | One confirmed software/data failure with robot telemetry still healthy | Phase-aware gait stop, zero velocity, and hold; do not sit or limp | Inspect camera and fresh telemetry; retry from a safe checkpoint if both are normal |
| One hot-temperature sample | Fewer than 3 consecutive over-threshold samples from the same joint and no controller thermal latch | Hold/continue the current safe controller while collecting confirmation samples; log the warning | Continue if it clears |
| Confirmed hot servo | Controller thermal latch or 3 consecutive over-threshold samples from the same joint | `X`, continue passive telemetry/video through cooldown, and do not reposition | Human inspection and explicit operator approval after 3 complete cool samples |
| Hard current, sustained overcurrent, real low voltage/brownout, tip/fall, collision, jam, or surprise force | Threshold logic or direct physical/camera evidence | `X` immediately; do **not** lower, sit, zero, plant, or retry | Human inspection and explicit operator approval |
| Implausible Euler-angle jump with quiet gyro | Discontinuous near-180-degree jump that contradicts measured angular rate | Reject that sample, log `tilt_glitch_ignored`, and keep collecting | Continue when trusted attitude samples remain normal |
| Sustained real excessive tilt | 3 valid consecutive samples, or direct camera evidence of a tip | `X`; preserve video and telemetry | Human inspection and explicit operator approval |
| Operator requests an ordinary pause/stop while stable | Direct operator request | Controlled gait/job stop and hold | Operator decides whether to resume or perform a planned lower |
| Operator presses the physical E-stop or reports immediate danger | Direct operator action/report | Treat as a confirmed hard stop | Human inspection and explicit operator approval |

An incomplete scan that stops publishing fresh timestamps is loss of
observability, not three missing-ID votes. If motion is active and health or a
controlled stop cannot be verified, use the telemetry-loss hard-stop path.

## Incident procedure

1. **Freeze the experiment state.** Do not advance to the next command or add
   a sit/stand/zero transition.
2. **Keep evidence.** Continue raw video, camera timestamps, robot telemetry,
   and the event log whenever the recorder is still healthy.
3. **Confirm the signal.** Use distinct fresh sample timestamps. Servo loss,
   temperature, tilt, and telemetry failures use the confirmation rules in the
   matrix; direct physical danger does not wait for voting.
4. **Stop with the minimum safe action.** A healthy active gait gets a
   phase-aware neutral stop and hold. A healthy stationary robot stays in its
   pose. A confirmed hard fault gets `X` and no additional body motion.
5. **Look at the robot.** Capture the current wide camera frame and the seconds
   immediately before the event. If the event identifies a leg, inspect a
   close view. Do not rotate or reposition the robot merely to improve the
   view until telemetry and the wide view show that motion is safe.
6. **Cross-check telemetry.** Record servo live/missing IDs and scan timestamp,
   temperature and joint name, current, voltage, trusted roll/pitch and gyro,
   controller activity, armed state, and the response endpoint result.
7. **Classify and record.** Mark the event as transient, non-hard run failure,
   soft warning, or confirmed hard fault. Record why, including the samples or
   image evidence that established the classification.
8. **Resume only by the applicable rule.** For the currently authorized test
   campaign, a transient or non-hard failure may continue after camera and
   fresh telemetry are normal. A confirmed hard fault never auto-resumes.

## Recovery boundaries

- A safe-zero, sit, stand, or plant is a separate planned motion. Never use one
  as a generic exception handler.
- Normal completion may include a planned lower and then `X`, but only with
  healthy feedback and a known posture. Log it as normal completion, not as an
  emergency recovery.
- Do not hold torque if the pose is fighting, jammed, stilted, tipped, hot, or
  drawing hard/sustained current. Those conditions require `X`.
- A supported single-joint grounded diagnostic may retry once after a
  confirmed current trip, but only after it has limped and feedback/current
  have recovered. A second quick failure ends the test limp.
- Do not automatically retry a gait, stand/plant blend, policy walk, tip,
  brownout, hot motor, persistent missing ID, jam, or surprise-force event.
- If the robot leaves the calibrated camera area during a healthy run, stop
  the gait neutrally, confirm the floor-map position, and return with bounded
  short pulses and a camera check after each pulse. Loss of visual localization
  means hold, not blind walking.

## Required event-log vocabulary

Use these names so summaries and the MCP experiment service can distinguish a
fault from a conservative pause:

- `transient_missing_servo_ignored`
- `tilt_glitch_ignored`
- `failure_pause_in_place_start`
- `failure_pause_holding_stationary_pose`
- `failure_pause_holding_walk_pose`
- `EMERGENCY_STOP`
- `thermal_cooldown_start` / `thermal_cooldown_complete`
- `operator_approval_required`

Every `EMERGENCY_STOP` record must include the confirmed reason. Never emit it
for a single missing reply or an ordinary stationary software failure.
