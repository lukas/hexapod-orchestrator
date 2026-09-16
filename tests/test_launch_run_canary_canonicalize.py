"""canary_update_error canonicalizes (meta 09-14) instead of bouncing.

28 REFUSED bounces in the 09-13/14 24h window were verdicts whose
--set status= carried a valid canary category ("FAIL-MECHANISM") but
whose verdict text lacked the literal CANARY tag; each bounce cost a
retry plus a re-grep of launch_run.py. The category the agent chose is
the semantics: canonicalize entry status/verdict in place, refuse only
when no category is named anywhere (bare FAIL stays ambiguous).
Mechanics-only, no ledger/pod/W&B access.
"""
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parents[1] / "orchestrator"
_spec = importlib.util.spec_from_file_location(
    "launch_run_canary", _HERE / "launch_run.py")
lr = importlib.util.module_from_spec(_spec)
sys.modules["launch_run_canary"] = lr
_spec.loader.exec_module(lr)

CUE = lr.canary_update_error


def _e(**kw):
    base = dict(phase="canary", run="cw-x-canary2m")
    base.update(kw)
    return base


def test_non_canary_phase_untouched():
    e = _e(phase="acquisition", status="FAIL-MECHANISM", verdict="flat")
    assert CUE(e) == ""
    assert e["verdict"] == "flat" and e["status"] == "FAIL-MECHANISM"


def test_hardware_ready_still_refused():
    assert "hardware_ready" in CUE(_e(hardware_ready=True))


def test_empty_verdict_ok():
    assert CUE(_e(status="RUNNING")) == ""


def test_tagged_verdict_passes_and_status_canonicalized():
    e = _e(status="CANARY FAIL-MECHANISM",
           verdict="CANARY FAIL - MECHANISM: lever engaged, rise flat")
    assert CUE(e) == ""
    assert e["status"] == "CANARY FAIL - MECHANISM"
    assert e["verdict"].startswith("CANARY FAIL - MECHANISM")
    assert e["verdict"].count("CANARY FAIL - MECHANISM") == 1  # no re-prefix


def test_bare_status_category_prepends_tag():
    e = _e(status="FAIL-MECHANISM",
           verdict="lever engaged, flat-start rise unchanged")
    assert CUE(e) == ""
    assert e["status"] == "CANARY FAIL - MECHANISM"
    assert e["verdict"] == ("CANARY FAIL - MECHANISM: lever engaged, "
                            "flat-start rise unchanged")


def test_bare_pass_status():
    e = _e(status="PASS", verdict="hold unregressed, depth clears bar")
    assert CUE(e) == ""
    assert e["status"] == "CANARY PASS"
    assert e["verdict"].startswith("CANARY PASS: ")


def test_fail_infra_spelling():
    e = _e(status="FAIL_INFRA", verdict="gravity ease leaked into hold")
    assert CUE(e) == ""
    assert e["status"] == "CANARY FAIL - INFRASTRUCTURE"


def test_bare_fail_stays_refused():
    e = _e(status="FAIL", verdict="did not work")
    assert "must name its category" in CUE(e)
    assert e["verdict"] == "did not work"  # untouched on refusal


def test_no_category_anywhere_refused():
    e = _e(status="FINISHED", verdict="reward flat, closing the class")
    assert "must name its category" in CUE(e)
