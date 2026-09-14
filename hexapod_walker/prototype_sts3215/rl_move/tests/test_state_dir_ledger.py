"""The ledger is a directory of per-entry files (2026-09-14): one JSON
object per ``ledger/<seq>-<run>.json``, where ``ledger_seq`` is assigned
once and never renumbered, so list order and duplicate run names survive
and a deletion leaves a gap; ``save_ledger`` touches only the files whose
content changed; the legacy single ``experiments.json`` is never read
silently. Mechanics only, temp dirs only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import state_dir

ORCH = Path(state_dir.__file__).resolve().parent


@pytest.fixture
def state(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "state"
    root.mkdir()
    monkeypatch.setattr(state_dir, "STATE_DIR", root)
    monkeypatch.setattr(state_dir, "LEDGER_DIR", root / "ledger")
    monkeypatch.setattr(state_dir, "LEDGER", root / "ledger")
    return root


def _entries(n: int) -> list[dict]:
    # duplicate names on purpose: retries reuse the run name
    return [{"run": f"cw-run-{i % 3}", "created": f"t{i}", "status": "RUNNING",
             "extra_args": ["--task", "walk"], "i": i} for i in range(n)]


def _snapshot(d: Path) -> dict[str, tuple[int, int]]:
    return {p.name: (p.stat().st_ino, p.stat().st_mtime_ns)
            for p in d.iterdir()}


def test_round_trip_preserves_order_and_duplicate_names(state):
    entries = _entries(7)
    state_dir.save_ledger(entries)
    names = sorted(p.name for p in (state / "ledger").iterdir())
    assert names[0] == "000001-cw-run-0.json"
    assert names[1] == "000002-cw-run-1.json"
    assert len(names) == 7 and len({n[7:] for n in names}) == 3
    assert [e["ledger_seq"] for e in entries] == list(range(1, 8))  # set in place
    assert state_dir.load_ledger() == entries
    assert json.loads((state / "ledger" / names[3]).read_text()) == entries[3]


def test_save_writes_only_changed_files(state):
    entries = _entries(6)
    state_dir.save_ledger(entries)
    before = _snapshot(state / "ledger")
    entries[2]["status"] = "FINISHED"
    entries.append({"run": "cw-new", "created": "t9"})
    state_dir.save_ledger(entries)
    after = _snapshot(state / "ledger")
    changed = {n for n in before if before[n] != after.get(n)}
    assert changed == {"000003-cw-run-2.json"}
    assert set(after) - set(before) == {"000007-cw-new.json"}
    assert state_dir.load_ledger() == entries
    # a no-op save touches nothing at all
    state_dir.save_ledger(entries)
    assert _snapshot(state / "ledger") == after


def test_delete_leaves_a_gap_and_never_renumbers(state):
    entries = _entries(5)
    state_dir.save_ledger(entries)
    before = _snapshot(state / "ledger")
    del entries[1]
    state_dir.save_ledger(entries)
    after = _snapshot(state / "ledger")
    assert set(before) - set(after) == {"000002-cw-run-1.json"}
    assert all(before[n] == after[n] for n in after)      # nothing rewritten
    assert [e["ledger_seq"] for e in state_dir.load_ledger()] == [1, 3, 4, 5]
    # appends continue after the highest seq ever used, not after len()
    entries.append({"run": "cw-after-gap"})
    state_dir.save_ledger(entries)
    assert entries[-1]["ledger_seq"] == 6
    assert (state / "ledger" / "000006-cw-after-gap.json").exists()
    state_dir.save_ledger([])
    assert list((state / "ledger").iterdir()) == []
    assert state_dir.load_ledger() == []


def test_run_rename_moves_the_file_and_keeps_the_seq(state):
    entries = _entries(2)
    state_dir.save_ledger(entries)
    entries[0]["run"] = "cw-renamed"
    state_dir.save_ledger(entries)
    names = sorted(p.name for p in (state / "ledger").iterdir())
    assert names == ["000001-cw-renamed.json", "000002-cw-run-1.json"]


def test_replaced_dict_without_seq_is_refused_not_reappended(state):
    entries = _entries(3)
    state_dir.save_ledger(entries)
    entries[0] = {"run": "cw-run-0", "created": "t0", "status": "FAILED"}
    with pytest.raises(ValueError, match="carry ledger_seq over"):
        state_dir.save_ledger(entries)
    assert state_dir.load_ledger()[0]["status"] == "RUNNING"   # nothing written
    entries[1] = dict(entries[1], ledger_seq=entries[2]["ledger_seq"])
    with pytest.raises(ValueError, match="two ledger entries carry"):
        state_dir.save_ledger(entries)
    with pytest.raises(TypeError, match="not a dict"):
        state_dir.save_ledger(["nope"])


def test_save_is_atomic_per_file_and_leaves_no_temp_files(state):
    state_dir.save_ledger(_entries(3))
    leftovers = [p for p in (state / "ledger").iterdir() if ".tmp" in p.name]
    assert leftovers == []
    name = state_dir.ledger_entry_name(1, {"run": "x"})
    tmp = (state / "ledger" / name).with_name(name + f".tmp{os.getpid()}")
    assert str(os.getpid()) in tmp.name   # per-writer temp name, no shared path


def test_entry_names_are_filesystem_safe(state):
    assert state_dir.ledger_entry_name(12, {"run": "a/b c:d"}) == "000012-a_b_c_d.json"
    assert state_dir.ledger_entry_name(1, {}) == "000001-unnamed.json"
    assert state_dir.ledger_entry_name(1, "not a dict") == "000001-unnamed.json"
    assert len(state_dir.ledger_entry_name(1, {"run": "r" * 500})) < 255
    state_dir.save_ledger([{"run": "../escape"}])
    assert [p.name for p in (state / "ledger").iterdir()] == ["000001-escape.json"]


def test_legacy_only_state_fails_loudly_and_is_never_read(state):
    (state / "experiments.json").write_text(json.dumps([{"run": "old"}]))
    with pytest.raises(RuntimeError, match="migrate-ledger"):
        state_dir.load_ledger()
    with pytest.raises(RuntimeError, match="migrate-ledger"):
        state_dir.save_ledger([{"run": "new"}])
    assert not (state / "ledger").exists()


def test_half_migrated_state_fails_loudly(state):
    state_dir.save_ledger([{"run": "a"}])
    (state / "experiments.json").write_text("[]")
    with pytest.raises(RuntimeError, match="half-finished"):
        state_dir.load_ledger()


def test_missing_state_dir_raises_instead_of_empty_ledger(state, monkeypatch):
    monkeypatch.setattr(state_dir, "LEDGER_DIR", state / "nowhere" / "ledger")
    with pytest.raises(FileNotFoundError, match="state dir missing"):
        state_dir.load_ledger()


def test_duplicate_seq_or_stray_file_is_an_error(state):
    state_dir.save_ledger(_entries(2))
    (state / "ledger" / "000002-other-name.json").write_text("{}")
    with pytest.raises(RuntimeError, match="two files for seq 2"):
        state_dir.load_ledger()
    (state / "ledger" / "000002-other-name.json").unlink()
    (state / "ledger" / "notes.json").write_text("{}")
    with pytest.raises(RuntimeError, match="notes.json"):
        state_dir.load_ledger()
    (state / "ledger" / "notes.json").unlink()
    (state / "ledger" / "000001-cw-run-0.json").write_text(
        json.dumps({"run": "cw-run-0", "ledger_seq": 7}))
    with pytest.raises(RuntimeError, match="does not match the file name"):
        state_dir.load_ledger()


def test_migration_is_equal_idempotent_and_keeps_the_source(state, capsys):
    src = _entries(9)
    (state / "experiments.json").write_text(json.dumps(src))
    capsys.readouterr()
    assert state_dir.migrate_ledger() == 0
    back = state_dir.load_ledger()
    assert [e["ledger_seq"] for e in back] == list(range(1, 10))
    assert [{k: v for k, v in e.items() if k != "ledger_seq"} for e in back] == src
    assert not (state / "experiments.json").exists()
    kept = list(state.glob("experiments.json.migrated-*"))
    assert len(kept) == 1 and json.loads(kept[0].read_text()) == src
    assert state_dir.migrate_ledger() == 0            # idempotent no-op
    assert "already migrated" in capsys.readouterr().out
    # a second legacy file appearing next to a populated dir needs --force
    (state / "experiments.json").write_text(json.dumps(src[:2]))
    assert state_dir.migrate_ledger() == 2
    assert state_dir.migrate_ledger(force=True) == 0
    assert [e["run"] for e in state_dir.load_ledger()] == [e["run"] for e in src[:2]]
    assert len(list((state / "ledger").iterdir())) == 2


def test_migration_cli_uses_HEXAPOD_STATE_DIR(state):
    src = [{"run": "cli-a"}, {"run": "cli-a"}]
    (state / "experiments.json").write_text(json.dumps(src))
    env = {**os.environ, "HEXAPOD_STATE_DIR": str(state), "UV_NO_PROJECT": "1"}
    r = subprocess.run([sys.executable, str(ORCH / "state_dir.py"), "migrate-ledger"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "migrated 2 entries" in r.stdout
    assert sorted(p.name for p in (state / "ledger").iterdir()) == [
        "000001-cli-a.json", "000002-cli-a.json"]
    r = subprocess.run([sys.executable, str(ORCH / "state_dir.py")],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.stdout.strip() == str(state)


def test_ledger_fingerprint_tracks_changes(state):
    state_dir.save_ledger(_entries(2))
    fp = state_dir.ledger_fingerprint()
    assert fp == state_dir.ledger_fingerprint()
    entries = state_dir.load_ledger()
    entries[0]["verdict"] = "PASS"
    state_dir.save_ledger(entries)
    assert state_dir.ledger_fingerprint() != fp
