"""Unit tests for launch_run.py's model-source continuity guard
(2026-08-25, gaitgate-scratch1/-cont1 dig-in): CURRENT_TRUTHS' SIM
MODEL CHANGE continuity rule ("any resume of a pre-08-24 checkpoint
MUST set env.model_source=primitive -- the families do NOT transfer")
had ZERO code enforcement, unlike the analogous control.hz rule -- a
--parent launch with no explicit env.model_source cfg-set silently
inherits whatever servo_model.resolve_model_source's code default is
at run time ("mesh" since commit 47110285), regardless of what family
the checkpoint being warm-started actually trained on. These tests
pin the pure-function contract directly (no I/O, no subprocess, no
pod, no real ledger).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCH = ROOT / "rl_move" / "orchestrator"
if str(ORCH) not in sys.path:
    sys.path.insert(0, str(ORCH))

import launch_run as lr  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_ledger_writes(monkeypatch):
    monkeypatch.setattr(lr, "upsert_entry", lambda entry: None)


def _fake_ledger(entries):
    return lambda: entries


# ---------------------------------------------------------------------
# _normalize_model_source
# ---------------------------------------------------------------------

def test_normalize_treats_mesh_mjx_as_mesh():
    assert lr._normalize_model_source("mesh") == "mesh"
    assert lr._normalize_model_source("mesh_mjx") == "mesh"
    assert lr._normalize_model_source("primitive") == "primitive"
    assert lr._normalize_model_source("") == "mesh"  # code default


# ---------------------------------------------------------------------
# _lineage_model_source
# ---------------------------------------------------------------------

def test_lineage_unknown_run_returns_none(monkeypatch):
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger([]))
    assert lr._lineage_model_source("no-such-run") is None


def test_lineage_explicit_override_wins(monkeypatch):
    ledger = [{"run": "r1", "parent": "",
               "extra_args": ["--cfg-set", "env.model_source=primitive"],
               "created": "2026-08-25T00:00:00+00:00"}]
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger(ledger))
    assert lr._lineage_model_source("r1") == "primitive"


def test_lineage_root_before_flip_is_primitive(monkeypatch):
    ledger = [{"run": "root", "parent": "", "extra_args": ["--n-envs", "1"],
               "created": "2026-08-24T18:00:00+00:00"}]
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger(ledger))
    assert lr._lineage_model_source("root") == "primitive"


def test_lineage_root_after_flip_is_mesh(monkeypatch):
    ledger = [{"run": "root", "parent": "", "extra_args": ["--n-envs", "1"],
               "created": "2026-08-25T00:00:00+00:00"}]
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger(ledger))
    assert lr._lineage_model_source("root") == "mesh"


def test_lineage_inherits_through_a_chain_with_no_override(monkeypatch):
    # root predates the flip (primitive); a later continuation (created
    # after the flip) with no explicit override must still resolve to
    # primitive via inheritance, not the child's own post-flip default.
    ledger = [
        {"run": "root", "parent": "", "extra_args": ["--n-envs", "1"],
         "created": "2026-08-24T18:00:00+00:00"},
        {"run": "child", "parent": "root", "extra_args": ["--n-envs", "1"],
         "created": "2026-08-25T02:00:00+00:00"},
    ]
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger(ledger))
    assert lr._lineage_model_source("child") == "primitive"


def test_lineage_prefers_the_ran_entry_over_a_thin_refused_stub(monkeypatch):
    ledger = [
        {"run": "r1", "parent": "", "wandb_id": "abc123",
         "extra_args": ["--cfg-set", "env.model_source=primitive"],
         "created": "2026-08-25T00:00:00+00:00"},
        {"run": "r1", "parent": "", "extra_args": ["--n-envs", "1"],
         "created": "2026-08-25T01:00:00+00:00"},
    ]
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger(ledger))
    assert lr._lineage_model_source("r1") == "primitive"


def test_lineage_cycle_guard_does_not_infinite_loop(monkeypatch):
    ledger = [
        {"run": "a", "parent": "b", "extra_args": ["--n-envs", "1"],
         "created": "2026-08-25T00:00:00+00:00"},
        {"run": "b", "parent": "a", "extra_args": ["--n-envs", "1"],
         "created": "2026-08-25T00:00:00+00:00"},
    ]
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger(ledger))
    # must terminate (depth cap) and return something, not hang/recurse-error
    assert lr._lineage_model_source("a") in ("mesh", "primitive", None)


# ---------------------------------------------------------------------
# _check_model_source_continuity
# ---------------------------------------------------------------------

def test_no_parent_is_a_no_op(monkeypatch):
    entry: dict = {}
    out = lr._check_model_source_continuity([], entry, "")
    assert out is None
    assert "refused_reason" not in entry


def test_unknown_lineage_is_skipped_not_blocked(monkeypatch):
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger([]))
    entry: dict = {}
    out = lr._check_model_source_continuity([], entry, "ghost-parent")
    assert out is None
    assert "refused_reason" not in entry
    assert entry["checks"]["model_source_lineage"] == "unknown"


def test_silent_mesh_default_onto_primitive_parent_refuses(monkeypatch):
    """The exact gaitgate-cont1 scenario: a --parent lineage that
    trained on primitive (pre-flip root, no override anywhere) is
    resumed with NO env.model_source cfg-set at all -- the launch
    would silently resolve to the post-flip mesh default. Must refuse."""
    ledger = [{"run": "primparent", "parent": "",
               "extra_args": ["--n-envs", "1"],
               "created": "2026-08-24T18:00:00+00:00"}]
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger(ledger))
    entry: dict = {}
    out = lr._check_model_source_continuity([], entry, "primparent")
    assert out == 1
    assert "primitive" in entry["refused_reason"]
    assert "mesh" in entry["refused_reason"]


def test_explicit_matching_primitive_passes(monkeypatch):
    ledger = [{"run": "primparent", "parent": "",
               "extra_args": ["--n-envs", "1"],
               "created": "2026-08-24T18:00:00+00:00"}]
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger(ledger))
    entry: dict = {}
    extra = ["--cfg-set", "env.model_source=primitive"]
    out = lr._check_model_source_continuity(extra, entry, "primparent")
    assert out is None
    assert "refused_reason" not in entry
    assert entry["checks"]["model_source_lineage"] == "primitive-matched"


def test_mesh_parent_with_default_mesh_child_passes(monkeypatch):
    ledger = [{"run": "meshparent", "parent": "",
               "extra_args": ["--cfg-set", "env.model_source=mesh"],
               "created": "2026-08-25T00:00:00+00:00"}]
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger(ledger))
    entry: dict = {}
    out = lr._check_model_source_continuity([], entry, "meshparent")
    assert out is None
    assert "refused_reason" not in entry


def test_allow_mismatch_escape_hatch_lets_a_deliberate_switch_through(
        monkeypatch):
    ledger = [{"run": "primparent", "parent": "",
               "extra_args": ["--n-envs", "1"],
               "created": "2026-08-24T18:00:00+00:00"}]
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger(ledger))
    entry: dict = {}
    out = lr._check_model_source_continuity(
        [], entry, "primparent", allow_mismatch=True)
    assert out is None
    assert "refused_reason" not in entry
    assert "explicit-mismatch" in entry["checks"]["model_source_lineage"]


def test_mesh_mjx_is_not_treated_as_a_mismatch_vs_mesh(monkeypatch):
    ledger = [{"run": "meshparent", "parent": "",
               "extra_args": ["--cfg-set", "env.model_source=mesh"],
               "created": "2026-08-25T00:00:00+00:00"}]
    monkeypatch.setattr(lr, "load_ledger", _fake_ledger(ledger))
    entry: dict = {}
    extra = ["--cfg-set", "env.model_source=mesh_mjx"]
    out = lr._check_model_source_continuity(extra, entry, "meshparent")
    assert out is None
    assert "refused_reason" not in entry
