# Hexapod emergency handling

This is the canonical response procedure for supervised physical-robot runs.
The goal is to stop hazardous motion without creating a second hazard through
an unnecessary sit, zero, plant, or torque-off transition.

The operator accepts that this robot is light, inexpensive, and presents low
consequence to people in its supervised floor test area. Two rules follow from
that and override any older, more cautious wording:

- **The three rule.** No guard fires on one reading. Every observation below
  needs **3 consecutive confirming samples** with distinct fresh timestamps
  before it counts as a fault, and every stopped step gets a budget of
  **3 attempts** before the campaign stops for a human.
- **Stop, wait, assess — do not park.** A fault stops motion immediately, but
  stopping is not the end of the run. Every stop below is followed by the
  [30-second assessment](#the-30-second-assessment). Only the operator's own
  E-stop, and a condition that is still present after 3 attempts, wait on a
  human.

An unattended overnight campaign must still be able to end itself: see
[Campaign budget](#campaign-budget).

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
| Persistent missing servo | 3 consecutive incomplete scans with distinct fresh timestamps | Stop and `X`; do **not** sit or safe-zero | 30-second assessment. If 3 fresh scans are 18/18 with normal electrical/thermal readings and the camera is normal, restart from a verified safe pose; 3 attempts |
| Telemetry/API read failure | Fewer than 3 consecutive attempts | Keep the current controller/pose and retry promptly; do not sit or limp | Continue after fresh telemetry confirms health |
| Telemetry lost while motion is active | 3 consecutive failures, or state/stop cannot be verified | Best-effort `X`; no blind recovery motion | 30-second assessment; the wait may extend while the link is down. On a normal camera view plus 3 complete healthy samples, restart from a verified safe pose; 3 attempts |
| Camera/tag/recorder/framework failure while stationary | One confirmed software/data failure with robot telemetry still healthy | Hold the current pose; keep any surviving logs open | 30-second assessment; retry from the last safe checkpoint if camera and telemetry are normal; 3 attempts |
| Camera/tag/recorder/framework failure while walking | One confirmed software/data failure with robot telemetry still healthy | Phase-aware gait stop, zero velocity, and hold; do not sit or limp | 30-second assessment; retry the complete failed step if camera and telemetry are normal; 3 attempts |
| One hot-temperature sample | Fewer than 3 consecutive over-threshold samples from the same joint and no controller thermal latch | Hold/continue the current safe controller while collecting confirmation samples; log the warning | Continue if it clears |
| Confirmed hot servo | Controller thermal latch or 3 consecutive over-threshold samples from the same joint | `X`, continue passive telemetry/video through cooldown, and do not reposition | Motors cool down: extend the assessment wait until 3 consecutive samples read cool and electrically healthy (recheck every 30 s, up to 10 min), then resume; 3 attempts. Hands-on only if it will not cool |
| Hard current, sustained overcurrent, real low voltage/brownout, tip/fall, collision, jam, or surprise force | 3 consecutive confirming samples, or direct physical/camera evidence | `X` immediately; do **not** lower, sit, zero, plant, or retry from the faulted pose | 30-second assessment. Camera plus 3 fresh electrical/thermal/motor samples showing a normal safe state clears it; retry from a verified safe pose, 3 attempts. Ask for hands-on only when the evidence still shows the fault |
| Implausible Euler-angle jump with quiet gyro | Discontinuous near-180-degree jump that contradicts measured angular rate | Reject that sample, log `tilt_glitch_ignored`, and keep collecting | Continue when trusted attitude samples remain normal |
| Sustained real excessive tilt | 3 valid consecutive samples, or direct camera evidence of a tip | `X`; preserve video and telemetry | 30-second assessment. Tilt alone is not a tip: a robot that reads past the envelope but is level in camera, or that a `sit` re-levels, is recoverable — re-run preflight and retry, 3 attempts. Hands-on only for an actual tip the robot cannot leave |
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
8. **Run the 30-second assessment, then resume by the applicable rule.** No
   stop ends the campaign by itself. Retry the complete failed step, not the
   remaining fragment, and allow 3 attempts. A physical or electrical hard
   fault never resumes blindly: first establish with a current camera view and
   recovered telemetry that the fault is no longer present, or obtain hands-on
   correction when remote evidence cannot.

## The 30-second assessment

Run this after every stop, including the ones that used to end the campaign.
Never leave the robot stopped and unexamined.

1. **Stop is already done.** The guard limped or held. Do not add motion.
2. **Wait 30 s.** Long enough for a bus to resettle, a link to come back, and
   a servo to shed heat; short enough that a healthy robot is not idle for an
   hour between one-minute experiments. A thermal stop extends this wait
   rather than skipping it.
3. **Re-read the evidence.** Take 3 fresh telemetry samples with distinct
   timestamps and one current camera frame.
4. **Decide, and write the decision down.**
   - *Fault absent* — the readings are normal and the camera shows a normal
     robot. Log `retry_after_assessment`, re-run the mode's preflight,
     restart the complete failed step from a verified safe pose.
   - *Fault present but self-clearing* — a hot motor still cooling, a link
     still down. Log `assessment_extended`, wait another 30 s, reassess. Cap
     the extension at 10 minutes, then treat it as still present.
   - *Fault still present* — log `hands_on_intervention_required` with the
     specific correction needed and stop the campaign.
5. **Count the attempt.** Three attempts at the same step, or three stops in a
   row across different steps, stops the campaign for a human.

An assessment that cannot be completed — no telemetry and no camera — counts
as *fault present*. Do not guess.

## Campaign budget

An unattended campaign must be able to end itself rather than burn a night on
a broken robot or a dark room:

- 3 attempts at any one step.
- 3 consecutive stopped experiments, regardless of step, ends the campaign.
- An assessment that cannot read telemetry or camera at all ends the campaign
  after its second occurrence: that is a powered-down robot or a dead link,
  and no amount of retrying fixes it.

Ending the campaign means: leave the robot limp and safe, write the reason,
and stop scheduling work. It does not mean holding the robot torqued.

## Recovery boundaries

- A safe-zero, sit, stand, or plant is a separate planned motion. Never use one
  as a generic exception handler.
- Normal completion may include a planned lower and then `X`, but only with
  healthy feedback and a known posture. Log it as normal completion, not as an
  emergency recovery.
- Do not hold torque if the pose is fighting, jammed, stilted, tipped, hot, or
  drawing hard/sustained current. Those conditions require `X`.
- A supported single-joint grounded diagnostic gets 3 attempts after a
  confirmed current trip, but only after it has limped and feedback/current
  have recovered. The third failed attempt ends the test limp.
- A gait or policy step gets 3 attempts after a recoverable signal, camera,
  recorder, or framework stop, once the 30-second assessment passes. Restart
  the whole step from a verified safe pose.
- A tip, visibly bad posture, stand/plant blend failure, brownout, hot motor,
  jam, surprise force, or hard/sustained current event is never retried *from
  the faulted pose* and never retried *immediately*. It goes through the
  30-second assessment like everything else, and retries from a verified safe
  pose when the evidence says the fault is gone.
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
- `recovery_evidence_required`
- `retry_after_assessment`
- `assessment_extended`
- `campaign_budget_exhausted`
- `hands_on_intervention_required`

Every `EMERGENCY_STOP` record must include the confirmed reason. Never emit it
for a single missing reply or an ordinary stationary software failure.
