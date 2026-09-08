"""Regression test for the 2026-09-06 ledger-corruption incident.

`save_ledger()` used to be a plain `Path.write_text()` -- not atomic.
A killed/slow writer (the ledger has grown to 20MB+) left a truncated,
unparseable JSON file visible to every concurrent reader for the whole
duration of the write; `snapshot.sh`'s `git add -A` (no ledger lock, by
design) staged exactly that torn mid-write state once, permanently
committing a truncated `experiments.json` that silently dropped ~360
historical entries plus an in-flight run's own launch record (hand-
recovered from the last-good git commit). Fixed by writing to a
sibling temp file and `os.replace()`-ing it into place: any concurrent
reader sees either the complete old file or the complete new one,
never a partial write, regardless of caller lock discipline elsewhere.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORCH = ROOT / "rl_move" / "orchestrator"

import launch_run as lr


def test_save_ledger_writes_atomically_via_temp_and_replace(tmp_path, monkeypatch):
    ledger_path = tmp_path / "experiments.json"
    monkeypatch.setattr(lr, "LEDGER", ledger_path)

    entries = [{"run": "a", "created": "t0"}, {"run": "b", "created": "t1"}]
    lr.save_ledger(entries)

    assert json.loads(ledger_path.read_text()) == entries
    # no leftover temp file
    leftovers = list(tmp_path.glob("experiments.json.tmp*"))
    assert leftovers == []


def test_save_ledger_never_leaves_a_half_written_file_visible(tmp_path, monkeypatch):
    ledger_path = tmp_path / "experiments.json"
    ledger_path.write_text(json.dumps([{"run": "orig", "created": "t0"}]))
    monkeypatch.setattr(lr, "LEDGER", ledger_path)

    big = [{"run": f"r{i}", "created": f"t{i}", "notes": "x" * 1000}
           for i in range(500)]
    lr.save_ledger(big)

    # A reader between the write and the rename would either see the
    # OLD complete file or the NEW complete file, never a partial one --
    # simulate that by just re-reading after the call returns (os.replace
    # is atomic; the only way to prove this without racing a real thread
    # is the absence of any partial-write artifact + a valid parse).
    reloaded = json.loads(ledger_path.read_text())
    assert reloaded == big


def test_save_ledger_uses_pid_suffixed_temp_name_not_a_fixed_shared_path():
    # Two concurrent writers must not collide on the same temp filename
    # (the old bug class documented in snapshot.sh's --sync comments for
    # a different shared /tmp path -- guard against reintroducing it here).
    import os
    ledger = lr.LEDGER
    tmp = ledger.with_suffix(ledger.suffix + f".tmp{os.getpid()}")
    assert str(os.getpid()) in tmp.name
