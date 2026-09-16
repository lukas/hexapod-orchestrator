"""Suite-wide fixtures.

Env pin: the calibrated behaviour tests were measured on the LEGACY
primitive sim model; ``setdefault`` keeps a deliberate outer override
working (a test that means the mesh family sets it with monkeypatch).
"""
import os
import shutil
import sys

import pytest

os.environ.setdefault("HEXAPOD_MODEL_SOURCE", "primitive")


def _state_dir_modules():
    """pytest.ini puts both `.` and `orchestrator/` on sys.path, so the
    module can be loaded as bare ``state_dir`` and as
    ``orchestrator.state_dir`` -- distinct objects; patch whichever exist."""
    import state_dir as bare
    mods = [bare]
    pkg = sys.modules.get("orchestrator.state_dir")
    if pkg is not None and pkg is not bare:
        mods.append(pkg)
    return mods


@pytest.fixture
def state_ledger(tmp_path, monkeypatch):
    """Temp state dir wired into state_dir; returns ``write(entries) -> Path``.

    ``write`` REPLACES the ledger with ``entries`` (numbered 1..N, the way
    the migration numbers a list) and returns the state dir. The caller's
    dicts are not mutated. Changed-file mechanics: test_state_dir_ledger.
    """
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
