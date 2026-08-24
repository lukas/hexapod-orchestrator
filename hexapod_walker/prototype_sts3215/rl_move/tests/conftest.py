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
"""
import os

os.environ.setdefault("HEXAPOD_MODEL_SOURCE", "primitive")
