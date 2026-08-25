"""Suite-wide default: pin the sim to the LEGACY primitive model family.

The behavior tests in this directory (recover rungs, catch teachers, gait
step events, spawn heights, ...) encode dynamics measured on the legacy
``mujoco_prototype`` robot (2.104 kg, hip axis on the yaw plane).  The
mesh-accurate family that ``env.model_source`` defaults to since 2026-08-24
(real CAD kinematics, as-built 3.5 kg masses) settles and loads its feet
differently, so those calibrated assertions do not transfer between the
families — running them against mesh would test nothing but the mismatch.

``HEXAPOD_MODEL_SOURCE`` overrides cfg resolution inside
``servo_model.resolve_model_source``; ``setdefault`` keeps a deliberate
outer override (e.g. a CI matrix leg) working.  Mesh-family coverage lives
in ``test_model_source.py``, which overrides per-test.

NOTE (2026-08-25 leg-sacrifice DIG-IN): `rl_move/config.py:load_config`
grew an analogous `HEXAPOD_CONTROL_HZ` override this same cycle while
chasing a 54-test full-bank regression (was 1 known-red 08-22) that
lines up with config.yaml's `control.hz` default flip 25->100 on 08-24.
It is DELIBERATELY NOT enabled here: forcing hz=25 on a sample
(`test_walk_gait_gate_*`) made the failures WORSE, not better (e.g.
flag-leg gate return-hit dropped from 369 at the current hz=100 default
to 37 at hz=25) — the hz flip is at most a partial contributor, not the
full explanation, and blindly pinning to the old rate is unvalidated and
was reverted rather than shipped. Root cause of the 54-test regression
is still OPEN; see OPERATOR_QUESTIONS.md 2026-08-25.
"""
import os

os.environ.setdefault("HEXAPOD_MODEL_SOURCE", "primitive")
