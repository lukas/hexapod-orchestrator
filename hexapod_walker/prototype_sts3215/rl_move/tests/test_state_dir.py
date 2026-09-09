"""Docs symlinked from the prototype tree into the state repo must still be
served (status_server /llm/doc, mcp_server read_doc). Regression for the
09-08 move: the traversal guard only accepted paths resolving under PROTO,
so every journal and run story 404'd."""
from __future__ import annotations

import os
import json

import pytest

import mcp_server
import state_dir
import status_server


def _layout(tmp_path, monkeypatch):
    proto = tmp_path / "proto"
    state = tmp_path / "state"
    (proto / "rl_docs" / "tracks" / "amp").mkdir(parents=True)
    (state / "rl_docs" / "tracks" / "amp").mkdir(parents=True)
    (state / "rl_docs" / "tracks" / "amp" / "STATUS.md").write_text("# amp\nhello\n")
    os.symlink(os.path.relpath(state / "rl_docs" / "tracks" / "amp" / "STATUS.md",
                               proto / "rl_docs" / "tracks" / "amp"),
               proto / "rl_docs" / "tracks" / "amp" / "STATUS.md")
    (tmp_path / "outside.md").write_text("nope\n")
    os.symlink(tmp_path / "outside.md", proto / "escape.md")
    monkeypatch.setattr(state_dir, "STATE_DIR", state)
    monkeypatch.setattr(status_server, "PROTO", proto)
    monkeypatch.setattr(mcp_server, "PROTO", proto)
    return proto


def test_status_server_serves_doc_symlinked_into_state(tmp_path, monkeypatch):
    _layout(tmp_path, monkeypatch)
    assert status_server.llm_doc_file("rl_docs/tracks/amp/STATUS.md") == b"# amp\nhello\n"


def test_status_server_still_refuses_symlink_escaping_both_roots(tmp_path, monkeypatch):
    _layout(tmp_path, monkeypatch)
    assert status_server.llm_doc_file("escape.md") is None
    assert status_server.llm_doc_file("../outside.md") is None


def test_mcp_read_doc_follows_state_symlink(tmp_path, monkeypatch):
    _layout(tmp_path, monkeypatch)
    out = mcp_server._read_doc("rl_docs/tracks/amp/STATUS.md")
    assert "hello" in (out if isinstance(out, str) else str(out))


@pytest.fixture
def alternate_state(tmp_path, monkeypatch):
    proto = _layout(tmp_path, monkeypatch)
    state = tmp_path / "alternate"
    docs = {
        "RL_LOG.md": "current cycle log\n",
        "rl_docs/SKILLS.md": "current skills\n",
        "OPERATOR_QUESTIONS.md": "current operator questions\n",
        "rl_docs/runs/fixture.md": "unique run story marker\n",
        "rl_docs/tracks/amp/STATUS.md": "current amp\n",
        "rl_docs/tracks/newtrack/STATUS.md": "current newtrack\n",
    }
    for rel, body in docs.items():
        p = state / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    (proto / "STATUS.md").write_text("code campaign digest\n")
    (state / "README.md").write_text("not a public logical doc\n")
    (state / "experiments.json").write_text(json.dumps([
        {"run": "fixture", "status": "FINISHED", "track": "amp"}]))
    # Keep the old code-tree link pointing to the original state. Readers
    # must use the configured clone even when that stale file still exists.
    monkeypatch.setenv("HEXAPOD_STATE_DIR", str(state))
    monkeypatch.setattr(state_dir, "STATE_DIR", state_dir.resolve_state_dir())
    monkeypatch.setattr(mcp_server, "LEDGER", state / "experiments.json")
    monkeypatch.setattr(status_server, "LEDGER", state / "experiments.json")
    monkeypatch.setattr(status_server._tracks, "load", lambda: {
        "amp": {"name": "AMP", "doc": "rl_docs/tracks/amp/STATUS.md"}})
    return proto, state, docs


def test_readers_use_configured_state_with_stale_or_missing_code_links(alternate_state):
    proto, state, docs = alternate_state
    for rel, body in docs.items():
        logical = ("rl_move/orchestrator/OPERATOR_QUESTIONS.md"
                   if rel == "OPERATOR_QUESTIONS.md" else rel)
        assert mcp_server._read_doc(logical) == body
        assert status_server.llm_doc_file(logical) == body.encode()
    assert mcp_server._read_doc("STATUS.md") == "code campaign digest\n"
    assert mcp_server.t_list_operator_questions() == docs["OPERATOR_QUESTIONS.md"]
    assert "current amp" in mcp_server.t_campaign_status()
    assert "current newtrack" in mcp_server.t_campaign_status()
    assert status_server.status_docs()["amp"]["text"] == "current amp\n"
    assert status_server.status_docs()["newtrack"]["text"] == "current newtrack\n"


def test_story_discovery_and_search_include_state_without_following_other_links(
        alternate_state, tmp_path):
    proto, state, docs = alternate_state
    (proto / "loop").symlink_to(proto, target_is_directory=True)
    (proto / "logs").mkdir()
    (proto / "logs/hidden.md").write_text("hidden log\n")
    outside = tmp_path / "outside.md"
    (state / "rl_docs/runs/escape.md").symlink_to(outside)
    indexed = mcp_server._doc_paths()
    assert indexed == status_server.list_docs()
    assert "rl_docs/runs/fixture.md" in indexed
    assert "rl_docs/tracks/newtrack/STATUS.md" in indexed
    assert "logs/hidden.md" not in indexed
    assert "README.md" not in indexed
    assert "rl_docs/runs/escape.md" not in indexed
    assert "escape.md" not in indexed
    assert "rl_docs/runs/fixture.md:1: unique run story marker" in (
        mcp_server.t_search_docs("unique run story marker"))
    assert "1 per-run stories" in mcp_server.t_list_docs()


def test_run_detail_surfaces_read_alternate_story(alternate_state, monkeypatch):
    monkeypatch.setattr(mcp_server, "feedback_for_run", lambda run: [])
    monkeypatch.setattr(status_server, "_cycle_registry_entries", lambda: [])
    monkeypatch.setattr(status_server, "representative_videos", lambda *a: {})
    assert "unique run story marker" in mcp_server.t_get_run("fixture")
    assert "unique run story marker" in status_server.render_run_page("fixture")


@pytest.mark.parametrize("rel", ["../outside.md", "/outside.md",
                                "rl_docs/runs/../SKILLS.md", "experiments.json"])
def test_document_path_rejects_non_doc_and_traversal(alternate_state, rel):
    assert state_dir.document_path(rel) is None


def test_missing_state_explains_sync_and_does_not_create_clone(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    monkeypatch.setattr(state_dir, "STATE_DIR", missing)
    monkeypatch.setattr(mcp_server, "PROTO", tmp_path)
    assert "make -C hexapod_walker/prototype_sts3215 state" in (
        mcp_server.t_read_doc("rl_docs/SKILLS.md"))
    assert not missing.exists()
