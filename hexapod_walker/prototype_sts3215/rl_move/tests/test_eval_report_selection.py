"""Report readers must not silently substitute a newer descendant's gate."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import subprocess

import pytest

ORCH = Path(__file__).resolve().parents[1] / "orchestrator"

import mcp_server

RUN = "cw-assistfade-rung3-residualfade-s0"
STEM = RUN.replace("-", "_")


def _report(proto, directory, *, std=0.052, mtime=1, session=False):
    path = proto / "logs" / "ckpt_eval" / directory / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"policy_std": std, "dr_scale": 0}
    if not session:
        data["episodes"] = {"walk/det": [{"gait_valid": True}] * 16}
    path.write_text(json.dumps(data))
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture(params=["mcp", "ops"])
def read_report(request, monkeypatch, tmp_path, capsys):
    """Exercise MCP and the real Python report block invoked by ops review."""
    monkeypatch.setattr(mcp_server, "PROTO", tmp_path)
    monkeypatch.setenv("PROTO", str(tmp_path))
    monkeypatch.setenv("HERE", str(ORCH))
    section = (ORCH / "ops.sh").read_text().split("\nreport) ", 1)[1]
    code = section.split("<<'EOF'\n", 1)[1].split("\nEOF", 1)[0]

    def read(query):
        if request.param == "mcp":
            return mcp_server.t_eval_report(query)
        monkeypatch.setattr(sys, "argv", ["-", query])
        try:
            exec(compile(code, str(ORCH / "ops.sh") + ":report", "exec"), {})
        except SystemExit as exc:
            return str(exc)
        return capsys.readouterr().out

    return read


def test_old_exact_gate_survives_newer_descendant_reports(tmp_path, read_report):
    _report(tmp_path, STEM + "_gate", mtime=1)
    _report(tmp_path, STEM + "_owncfg", mtime=2)
    _report(tmp_path, STEM + "_session", mtime=3, session=True)
    for i, variant in enumerate(("nostdanneal_gate", "nostdanneal_owncfg",
                                  "nostdanneal_session", "stdslow_gate"), 10):
        _report(tmp_path, STEM + "_" + variant, std=0.422, mtime=i)

    output = read_report(RUN)

    assert "0.052" in output
    assert "0.422" not in output
    assert "nostdanneal" not in output
    assert "4 other name matches excluded" in output
    assert output.index(STEM + "_gate/report.json") < output.index(
        STEM + "_owncfg/report.json") < output.index(STEM + "_session/report.json")
    assert "FALLBACK" not in output


def test_missing_exact_gate_marks_descendant_as_fallback(tmp_path, read_report):
    _report(tmp_path, STEM + "_nostdanneal_gate", std=0.422)

    output = read_report(RUN)

    assert "FALLBACK: no exact report directory" in output
    assert "may be variants or different runs" in output
    assert STEM + "_nostdanneal_gate/report.json" in output
    assert "0.422" in output


@pytest.mark.parametrize("suffix", ["nostdanneal_gate", "gate_recheck_20260907"])
def test_explicit_variant_query_stays_accessible(tmp_path, read_report, suffix):
    _report(tmp_path, STEM + "_gate", mtime=100)
    _report(tmp_path, STEM + "_" + suffix, std=0.422, mtime=1)

    output = read_report(STEM + "_" + suffix)

    assert STEM + "_" + suffix + "/report.json" in output
    assert "0.422" in output
    assert "0.052" not in output
    assert "FALLBACK" not in output


def test_longer_sibling_without_boundary_does_not_mask_missing_report(
        tmp_path, read_report):
    _report(tmp_path, "cw_demo_acq1b_gate")

    output = read_report("cw-demo-acq1")

    assert "no " in output and "report" in output and "matching" in output
    assert "cw_demo_acq1b" not in output


def test_historical_cw_walk_prefix_omission(tmp_path, read_report):
    _report(tmp_path, "demo_s0_gate")

    output = read_report("cw-walk-demo-s0")

    assert "demo_s0_gate/report.json" in output
    assert "0.052" in output
    assert "FALLBACK" not in output


def test_ops_explicit_json_path_is_unchanged(monkeypatch, tmp_path, capsys):
    path = _report(tmp_path, STEM + "_gate_recheck", std=0.422)
    monkeypatch.setenv("PROTO", str(tmp_path))
    monkeypatch.setenv("HERE", str(ORCH))
    monkeypatch.setattr(sys, "argv", ["-", str(path)])
    section = (ORCH / "ops.sh").read_text().split("\nreport) ", 1)[1]
    code = section.split("<<'EOF'\n", 1)[1].split("\nEOF", 1)[0]

    exec(compile(code, str(ORCH / "ops.sh") + ":report", "exec"), {})

    output = capsys.readouterr().out
    assert STEM + "_gate_recheck/report.json" in output
    assert "std=0.422" in output
    assert "FALLBACK" not in output


@pytest.mark.parametrize("selection", ["exact", "explicit_variant", "fallback"])
def test_review_pairs_report_with_media_from_same_experiment(tmp_path, selection):
    """Run the whole review shell; only the unrelated W&B API is stubbed."""
    local_orch = tmp_path / "rl_move" / "orchestrator"
    local_orch.mkdir(parents=True)
    for filename in ("ops.sh", "eval_reports.py"):
        (local_orch / filename).write_bytes((ORCH / filename).read_bytes())
    (local_orch / "experiments.json").write_text("[]")
    (tmp_path / "wandb.py").write_text(
        "class Api:\n    def runs(self, *args, **kwargs):\n        return []\n")
    query = RUN
    wanted = STEM + "_gate"
    other = STEM + "_nostdanneal_gate"
    if selection != "fallback":
        _report(tmp_path, STEM + "_gate", mtime=1)
    _report(tmp_path, STEM + "_nostdanneal_gate", std=0.422, mtime=100)
    for report in (tmp_path / "logs" / "ckpt_eval").glob("*/report.json"):
        for name in ("walk_det_0.mp4", "walk_det_0.png"):
            media = report.parent / name
            media.write_bytes(b"fixture")
            os.utime(media, (report.stat().st_mtime, report.stat().st_mtime))
    if selection != "exact":
        wanted, other = other, wanted
        if selection == "explicit_variant":
            query = wanted

    result = subprocess.run(
        ["bash", str(local_orch / "ops.sh"), "review", query],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True, text=True, check=True, timeout=30)

    report_output, media_output = result.stdout.split("##### eval report", 1)[1].split(
        "##### videos / contact sheets", 1)
    assert wanted + "/report.json" in report_output
    assert wanted + "/walk_det_0.mp4" in media_output
    assert wanted + "/walk_det_0.png" in media_output
    assert other + "/report.json" not in report_output
    assert other + "/walk_det_0" not in media_output
    assert ("FALLBACK" in report_output) == (selection == "fallback")
    assert ("FALLBACK" in media_output) == (selection == "fallback")
