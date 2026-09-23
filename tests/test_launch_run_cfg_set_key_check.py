"""Unit tests for launch_run.py's --cfg-set key validator (2026-09-23
meta: a stray `--cfg-set dr_scale=0.6` -- the real knob is the CLI flag
--dr-scale -- was a SILENT NO-OP at train time, so one run trained at
the wrong DR and drew a wrong verdict before correction; a sibling
crashed pre-init on the same typo. parse_cfg_set accepts any key, and
consumers .get() with defaults, so an unknown key never errors). A key
is valid iff it resolves as a dotted path in rl_move/config.yaml, or
(dotted keys only) its full quoted literal or bare-word leaf appears in
rl_move source. Dot-less keys must be top-level config.yaml keys --
every historical dot-less cfg-set was a typo."""
from __future__ import annotations

import launch_run as lr

import pytest


@pytest.fixture(autouse=True)
def _no_real_ledger_writes(monkeypatch):
    monkeypatch.setattr(lr, "upsert_entry", lambda entry: None)


def _check(extra, **kw):
    entry = {"checks": {}}
    return lr._check_cfg_set_keys(extra, entry, **kw), entry


def test_dotless_typo_refused():
    rc, _ = _check(["--cfg-set", "dr_scale=0.6"])
    assert rc == 1


def test_dotted_typo_refused():
    rc, _ = _check(["--cfg-set", "reward.k_walk_move_curent=5"])
    assert rc == 1


def test_leading_quote_artifact_refused():
    # a quoting bug upstream stored the key WITH its shell quote --
    # also a silent no-op at train time
    rc, _ = _check(["--cfg-set", "'goal.rise_height_mm=[100,140]"])
    assert rc == 1


def test_config_yaml_path_ok():
    rc, _ = _check(["--cfg-set", "env.model_source=primitive"])
    assert rc is None


def test_trainer_literal_key_ok():
    # consumed via _parse_cfg_set(...).get("ppo.bc_anchor_coef")
    rc, _ = _check(["--cfg-set", "ppo.bc_anchor_coef=0.0"])
    assert rc is None


def test_section_dict_leaf_key_ok():
    # consumed attribute/leaf-style, never as a full dotted literal
    rc, _ = _check(["--cfg-set", "dr.imu_mount_deg=2.0"])
    assert rc is None


def test_allow_unknown_flag_bypasses_and_records():
    rc, entry = _check(["--cfg-set", "dr_scale=0.6"], allow_unknown=True)
    assert rc is None
    assert "dr_scale" in entry["checks"]["cfg_set_keys"]


def test_non_cfg_set_args_ignored():
    rc, _ = _check(["--seed", "3", "--dr-scale", "0.6"])
    assert rc is None
