"""Regression test for the 2026-09-06 ledger-corruption incident.

`save_ledger()` used to be a plain `Path.write_text()` -- not atomic.
A killed/slow writer (the ledger had grown to 20MB+) left a truncated,
unparseable JSON file visible to every concurrent reader for the whole
duration of the write; `snapshot.sh`'s `git add -A` staged exactly that
torn mid-write state once, permanently committing a truncated
`experiments.json` that silently dropped ~360 historical entries. Since
2026-09-14 the ledger is a directory of per-entry files (state_dir.py)
and each file is written to a pid-suffixed sibling temp file and
`os.replace()`-d into place, so a reader sees either the complete old
entry or the complete new one, never a partial write. launch_run's
`load_ledger`/`save_ledger` ARE state_dir's -- this locks that in.
"""
from __future__ import annotations

import json
import os

import launch_run as lr
import state_dir


def test_launch_run_accessors_are_state_dirs():
    assert lr.load_ledger is state_dir.load_ledger
    assert lr.save_ledger is state_dir.save_ledger
    assert not hasattr(lr, "LEDGER")          # no second path to the ledger


def test_save_ledger_writes_atomically_via_temp_and_replace(state_ledger):
    entries = [{"run": "a", "created": "t0"}, {"run": "b", "created": "t1"}]
    root = state_ledger([])
    lr.save_ledger(entries)
    files = sorted((root / "ledger").iterdir())
    assert [p.name for p in files] == ["000001-a.json", "000002-b.json"]
    assert json.loads(files[0].read_text()) == entries[0]
    assert lr.load_ledger() == entries
    assert [p for p in (root / "ledger").iterdir() if ".tmp" in p.name] == []


def test_save_ledger_never_leaves_a_half_written_file_visible(state_ledger):
    root = state_ledger([{"run": "orig", "created": "t0"}])
    big = [{"run": f"r{i}", "created": f"t{i}", "notes": "x" * 1000}
           for i in range(500)]
    lr.save_ledger(big)
    # every file parses on its own; the dropped original is gone
    for p in (root / "ledger").iterdir():
        json.loads(p.read_text())
    assert lr.load_ledger() == big


def test_save_ledger_uses_pid_suffixed_temp_name_not_a_fixed_shared_path(state_ledger, monkeypatch):
    # Two concurrent writers must not collide on the same temp filename
    # (the old bug class documented in snapshot.sh's --sync comments for
    # a different shared /tmp path -- guard against reintroducing it here).
    root = state_ledger([])
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(os.path.basename(src))
        real_replace(src, dst)
    monkeypatch.setattr(state_dir.os, "replace", spy)
    lr.save_ledger([{"run": "a"}])
    assert seen == [f"000001-a.json.tmp{os.getpid()}"]
