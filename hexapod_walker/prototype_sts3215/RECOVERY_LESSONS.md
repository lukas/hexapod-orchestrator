# H1 recovery lessons — 2026-09-14

This retrospective records hours lost during H1 recovery so the next agent
changes the approach, rather than reproducing the same trials.

## What actually succeeded

The existing Safe Zero routine eventually completed: maximum reported absolute
logical joint angle was about **0.7°**, feedback was **18/18**, maximum temperature
was **32°C**, and maximum reported current was **0.013 A**. The body remained on
the floor. This established recovery to the zero pose, **not standing or walking**.

This particular invocation used `/api/safe_zero` with `force: true`, after
low-current hip preparation brought L4's logical tibia angle within 150°.
Geometric checks and motor guards remained active. This is evidence for that
observed starting state, not an instruction to always force Safe Zero or use
it as a generic fault response. Consult [the route](linux_control/api/zero.py)
and [its executor](linux_control/safe_zero.py) for current behavior.

## Messages to the next agent

1. **Inventory proven routines before inventing recovery profiles.** Read the
   existing Safe Zero, stand and recovery routes and their entry conditions.
   Safe Zero succeeded after many conservative custom nudges failed to deliver
   the intended recovery. That does not establish torque as the sole cause:
   the path, starting geometry and support behavior also changed.

2. **Measure the physical objective.** Commands intended to stand on the other
   five feet never established an observed five-leg stand. Partial encoder
   motion, a settled target or low current does not prove foot contact, body
   lift or unloading of the trapped leg. Record those observations separately,
   including whether the improvement survives the end of the command.

3. **Plan how support survives an ordinary completion.** The custom recovery
   primitive's unconditional all-off cleanup repeatedly relaxed the legs and
   lost the support gained during each attempt. A healthy pause needs an
   appropriate supervised hold or a controlled return along a known path.
   Do not merely remove cleanup and leave torque on indefinitely. Keep one
   control owner, a bounded end plan and an available abort. Choose hold,
   controlled stop or limp using [EMERGENCY_HANDLING.md](EMERGENCY_HANDLING.md);
   confirmed faults still require its response.

4. **Check the angle frame at the write boundary.** A raw hip angle is a servo
   hinge coordinate; a raw knee angle is relative to the femur; an API knee
   angle describes the absolute tibia orientation. With unit signs and zero
   trims, absolute tibia angle is hip plus relative knee. Do not assume those
   conditions: inspect the current conversion, signs and trims in
   [feetech_bus.py](motor_setup/feetech_bus.py) and
   [mcu_feetech_bus.py](linux_control/mcu_feetech_bus.py). A scalar raw write and
   a converted full-pose write have different contracts. Calibration changes
   also affect interpretation; an encoder number alone does not establish a
   physical straight pose.

5. **Change strategy when bounded trials produce no physical progress.** Name
   the expected physical change and the observation that would disprove the
   hypothesis before the next trial. At the end of the bounded attempt budget,
   record the result and change strategy if that change is absent. Do not spend
   hours adjusting residual tolerances, torque caps and durations while the
   body remains on the floor. This is a strategy checkpoint, not another
   permission gate; standing authorization remains in force.

6. **Resolve camera identity and orientation from evidence.** Use tags,
   landmarks and known observed motion to identify legs and directions. Screen
   left/right and camera numbering are not robot coordinates. An occluded foot
   is not proven free or grounded; IMU tilt is not body height. Use visible
   floor references and complementary views to establish clearance.

7. **Collect evidence that can change the next action.** Reuse the
   [observation helper](linux_control/ROBOT_OBSERVE.md) instead of duplicating
   ad hoc camera, telemetry and artifact commands. Add a diagnostic only for a
   concrete unresolved question. More logs and new profiles are not physical
   progress. Output/PWM percentage is not measured shaft torque, and current
   alone cannot distinguish contact, friction and load.

The campaign's trial reports and recordings are under
`artifacts/h1-codex-recovery2-20260914/` in the main checkout. Preserve the
distinction between commands issued, motion observed and outcomes verified
when adding evidence or reporting readiness.
