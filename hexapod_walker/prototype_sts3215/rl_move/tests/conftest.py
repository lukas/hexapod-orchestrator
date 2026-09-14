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

NOTE (2026-09-08, operator): the MDP_PREFLIGHT rollout bank
(``test_task_semantics.py``) is retired and this primitive pin is now a
LEGACY default for the remaining calibrated tests only. New tests set the
family they mean explicitly with ``monkeypatch.setenv("HEXAPOD_MODEL_SOURCE",
"mesh")`` and never write ``os.environ`` directly (RESEARCH_RULES "Tests").

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


# ---------------------------------------------------------------------------
# Ledger fixture (2026-09-14): the ledger is a directory of per-entry files
# behind state_dir.load_ledger/save_ledger. Tests that used to write a JSON
# list to a temp `experiments.json` and monkeypatch `<module>.LEDGER` now
# point state_dir at a temp state dir and write through the real accessor.
# ---------------------------------------------------------------------------
import pytest  # noqa: E402


def _state_dir_modules():
    """Both import spellings of state_dir that the suite can produce (the
    bare orchestrator module and rl_move.orchestrator.state_dir) are
    distinct module objects; patch whichever exist."""
    import state_dir as bare
    mods = [bare]
    try:
        from rl_move.orchestrator import state_dir as pkg
    except ImportError:  # pragma: no cover - depends on the import path
        pkg = None
    if pkg is not None and pkg is not bare:
        mods.append(pkg)
    return mods


@pytest.fixture
def state_ledger(tmp_path, monkeypatch):
    """Temp state dir wired into state_dir; returns ``write(entries) -> Path``.

    ``write`` REPLACES the ledger with ``entries`` (numbered 1..N, the way
    the migration numbers a list) and returns the state dir -- the same
    semantics the old ``path.write_text(json.dumps(rows))`` fixtures had.
    The caller's dicts are not mutated. Call it with ``[]`` for an empty
    ledger. Changed-file mechanics are tested in test_state_dir_ledger.
    """
    import shutil

    import state_dir
    root = tmp_path / "state"
    root.mkdir(exist_ok=True)
    for mod in _state_dir_modules():
        monkeypatch.setattr(mod, "STATE_DIR", root)
        monkeypatch.setattr(mod, "LEDGER_DIR", root / "ledger")
        monkeypatch.setattr(mod, "LEDGER", root / "ledger")

    def write(entries):
        shutil.rmtree(root / "ledger", ignore_errors=True)
        state_dir.save_ledger([
            {k: v for k, v in e.items() if k != state_dir.SEQ_KEY}
            for e in entries])
        return root
    return write
