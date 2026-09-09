"""Pure overseer decisions. Observations are data, never executable instructions."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any

REVIEW_SECONDS = 6 * 60 * 60
SPEND_THRESHOLD = Decimal("100")
ACTIVE = {"active", "running", "in_progress", "inprogress"}
PAUSED = {"paused", "disabled", "stopped_by_operator"}
TERMINAL = {"succeeded", "failed", "dead", "finished", "completed", "cancelled"}
GOALS = {"any_means", "rl_only"}
AUTH = re.compile(r"authenticationerror|authentication failed|invalid.{0,20}api.?key|verifying the api key|expired credential|unauthorized", re.I)


def timestamp(value: str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def age_seconds(value: str | None, now: datetime) -> float | None:
    try:
        if not value:
            return None
        elapsed = (now - timestamp(value)).total_seconds()
        return max(0.0, elapsed) if elapsed >= -60 else None
    except (ValueError, TypeError):
        return None


def money(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except InvalidOperation:
        return None


def status(record: dict) -> str:
    return str(record.get("status", record.get("state", "unknown"))).lower()


def text_evidence(record: dict) -> list[str]:
    evidence = record.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = [evidence]
    return [str(item)[:800] for item in evidence[:12]]


def finding(code: str, subject: str, severity: str, detail: str,
            proposed: str, *, evidence: list[str] | None = None,
            owner: str = "project owner", notify: bool = False) -> dict:
    incident_id = hashlib.sha256(f"{code}:{subject}".encode()).hexdigest()[:24]
    return {"incident_id": incident_id, "code": code, "subject": subject,
            "severity": severity, "detail": detail, "evidence": evidence or [],
            "proposed_action": proposed, "execution_owner": owner,
            "notify": notify, "executed": False}


def reflection(record: dict) -> dict:
    """A self-assessment is useful context, not independent proof of progress."""
    source = record.get("assessment") or record.get("self_assessment") or {}
    if not isinstance(source, dict):
        source = {}
    return {"agent_id": record.get("agent_id"), "goals": record.get("goals", []),
            "scope": record.get("scope", "unknown"),
            "claimed_progress": source.get("progress", source.get("what_changed")),
            "evidence": source.get("evidence", record.get("progress_evidence", [])),
            "recommendation": source.get("decision", "review needed"),
            "next_step": source.get("next_step"),
            "verification": "self-reported; check linked artifacts independently"}


def evaluate(snapshot: dict, *, history: dict | None = None,
             now: str | None = None, force: bool = False) -> dict:
    """Return an advisory plan. This function cannot invoke tools or send messages.

    Fresh events, new unreviewed spend and overdue active work can request a
    review. An unchanged incident never purchases another session merely
    because the six-hour timer fired. Intentional pause is not a fault.
    """
    current = timestamp(now)
    history = history or {}
    agents = snapshot.get("agents", [])
    services = snapshot.get("services", [])
    if not isinstance(agents, list) or not isinstance(services, list):
        raise ValueError("agents and services must be lists")
    agents = [dict(a) if isinstance(a, dict) else a for a in agents]
    overseer_ids = {a.get('agent_id') for a in agents if isinstance(a,dict)
                    and (a.get('is_overseer') or a.get('overseer_wake_id'))}
    # Propagate self-attribution through registered parent chains with a cycle guard.
    for _ in range(len(agents)):
        descendants = {a.get('agent_id') for a in agents if isinstance(a,dict)
                       and a.get('parent_id') in overseer_ids}
        if descendants <= overseer_ids:
            break
        overseer_ids.update(descendants)
    for a in agents:
        if isinstance(a, dict) and a.get('agent_id') in overseer_ids:
            a['is_overseer'] = True
    findings: list[dict] = []
    active: list[dict] = []
    unknown_cost: list[str] = []
    spend_due: list[str] = []
    progress_due: list[str] = []
    resources: dict[str, list[str]] = defaultdict(list)
    provenance_gaps: list[str] = []
    task_spend: dict[str, Decimal] = defaultdict(Decimal)
    task_agents: dict[str, list[str]] = defaultdict(list)
    for agent in agents:
        if not isinstance(agent, dict):
            raise ValueError("agent entries must be objects")
        if agent.get("is_overseer") or agent.get("overseer_wake_id"):
            continue
        amount = money(agent.get("unreviewed_cost_usd"))
        if amount is not None:
            task = str(agent.get("task_id") or agent.get("agent_id"))
            task_spend[task] += amount
            task_agents[task].append(str(agent["agent_id"]))
    for task, amount in sorted(task_spend.items()):
        if amount >= SPEND_THRESHOLD:
            spend_due.extend(task_agents[task])
            findings.append(finding("spend_review", task, "review",
                f"${amount:.2f} of reported spending across this logical task has not been reviewed.",
                "Review goal progress and repeated operations. Propose a bounded automation job only when log evidence supports it; charge any subagent to this wake.",
                evidence=task_agents[task], owner="overseer"))
    for agent in agents:
        if not isinstance(agent, dict):
            raise ValueError("agent entries must be objects")
        aid = str(agent.get("agent_id", "unknown"))
        # Overseer and its descendants cannot create a self-funding wake loop.
        is_overseer = bool(agent.get("is_overseer") or agent.get("overseer_wake_id"))
        state = status(agent)
        observed = age_seconds(agent.get("observed_at", snapshot.get("collected_at")), current)
        fresh = observed is not None and observed <= 15 * 60
        if state in ACTIVE and fresh and not is_overseer:
            active.append(agent)
            for resource in agent.get("resources", []):
                resources[str(resource)].append(aid)
            if not set(agent.get("goals", [])) & GOALS:
                provenance_gaps.append(aid)
            progress_age = age_seconds(agent.get("last_progress_at"), current)
            start_age = age_seconds(agent.get("started_at"), current)
            if (progress_age is not None and progress_age >= REVIEW_SECONDS
                    and start_age is not None and start_age >= REVIEW_SECONDS):
                progress_due.append(aid)
                findings.append(finding("progress_review", aid, "review",
                    "Active work has no recorded progress checkpoint for six hours; this alone does not prove a loop.",
                    "Inspect the current task, child/trainer progress and new evidence; request a short continue/change/stop assessment.",
                    evidence=text_evidence(agent), owner="current task owner"))
        elif state in ACTIVE and not fresh:
            findings.append(finding("stale_observation", aid, "info",
                "Reported activity lacks a fresh observation.",
                "Refresh status before deciding whether to stop or restart anything.",
                evidence=text_evidence(agent)))
        if not is_overseer:
            if agent.get("cost_status") != "known":
                unknown_cost.append(aid)
        loop = agent.get("loop_evidence") or {}
        # Idle sessions and repeated tool names are NOT evidence of a loop.
        if (state in ACTIVE and fresh and not is_overseer and isinstance(loop, dict)
                and isinstance(loop.get("same_failure_count"), (int, float))
                and not isinstance(loop.get("same_failure_count"), bool)
                and loop["same_failure_count"] >= 3
                and isinstance(loop.get("window_seconds"), (int, float))
                and not isinstance(loop.get("window_seconds"), bool)
                and loop["window_seconds"] >= 1800
                and loop.get("unchanged_progress") is True
                and loop.get("no_progressing_children") is True
                and loop.get("failure_signature") and loop.get("operation")):
            findings.append(finding("suspected_loop", aid, "warning",
                "Repeated same-operation failures with unchanged progress warrant an owner review.",
                "Verify the repeated failure against logs, then ask the registered owner for a cooperative stop. Preserve healthy trainers/checkpoints; hardware needs its guarded stop path.",
                evidence=text_evidence(agent), owner="registered execution owner", notify=True))
    for resource, owners in resources.items():
        if len(set(owners)) > 1:
            findings.append(finding("ownership_conflict", resource, "warning",
                "Multiple active agents report owning the same exclusive resource.",
                "Resolve ownership before additional mutations; do not kill a process based on its name.",
                evidence=sorted(set(owners)), notify=True))
    for service in services:
        sid = str(service.get("service_id", service.get("name", "unknown-service")))
        evidence = text_evidence(service)
        desired = str(service.get("desired_state", "unknown")).lower()
        observed = age_seconds(service.get("observed_at", snapshot.get("collected_at")), current)
        fresh = observed is not None and observed <= 15 * 60
        auth_evidence = [line for line in evidence if AUTH.search(line)]
        auth_count = service.get("auth_failure_count", service.get("failure_count", len(auth_evidence)))
        persistent_auth = bool(service.get("auth_failure") or auth_evidence) and isinstance(auth_count, (int, float)) and auth_count >= 3
        if desired in PAUSED or status(service) in PAUSED:
            findings.append(finding("intentional_pause", sid, "info",
                "The saved desired state is paused or disabled.",
                "Leave it paused. A monitor must not interpret intentional shutdown as a recovery request.",
                evidence=evidence, owner=str(service.get("owner", "operator"))))
        auth_age = age_seconds(service.get("last_auth_failure_at", service.get("observed_at")), current)
        auth_fresh = auth_age is not None and auth_age <= 15 * 60
        if persistent_auth and fresh and auth_fresh:
            repair = ("Read-only authentication diagnosis only while intentionally paused; do not restart it. "
                      if desired in PAUSED or status(service) in PAUSED else
                      "Verify the failing integration and try only its documented credential refresh/reload, at most twice per incident. ")
            findings.append(finding("authentication_failure", sid, "warning",
                "Repeated authentication failures are preventing reliable status/progress checks.",
                repair + "If that fails or no supported repair exists, notify Lukas once with the failed step and required action. Never expose keys or relax access controls.",
                evidence=auth_evidence or evidence, owner=str(service.get("owner", "service owner")), notify=True))
        elif persistent_auth:
            findings.append(finding("stale_authentication_report", sid, "info",
                "Authentication errors are present in an old or undated observation.",
                "Fetch fresh service status before opening a new incident.", evidence=evidence))
    # A resolved incident can recur, while repeated observations share one ID.
    for item in findings:
        base = item["incident_id"]
        previous = history.get("incident_episodes", {}).get(base, {})
        episode = int(previous.get("episode", 1))
        if previous.get("status") in {"resolved", "declined"}:
            episode += 1
        item["base_incident_id"] = base
        item["episode"] = episode
        item["incident_id"] = (base if episode == 1 else
            hashlib.sha256(f"{base}:{episode}".encode()).hexdigest()[:24])
    seen = set(history.get("reviewed_incidents", []))
    new_incidents = [f["incident_id"] for f in findings
                     if f["severity"] == "warning" and f["incident_id"] not in seen]
    last = age_seconds(history.get("last_review_at"), current)
    six_hour_due = bool(active) and (last is None or last >= REVIEW_SECONDS)
    unchanged = False
    fingerprint_data = [{"id": a.get("agent_id"), "status": status(a),
        "progress": a.get("last_progress_at"), "evidence": a.get("progress_evidence", []),
        "blocker": a.get("blocker"), "spend": a.get("unreviewed_cost_usd")}
        for a in agents if not a.get("is_overseer") and not a.get("overseer_wake_id")]
    fingerprint_data.sort(key=lambda a: str(a["id"]))
    dependencies = sorted([{'id':s.get('service_id',s.get('name')), 'status':status(s),
        'desired_state':s.get('desired_state'), 'auth_failure':s.get('auth_failure'),
        'auth_recovery_status':s.get('auth_recovery_status'), 'dependency_version':s.get('dependency_version')}
        for s in services], key=lambda s: str(s['id']))
    fingerprint = hashlib.sha256(json.dumps({'agents':fingerprint_data,'dependencies':dependencies}, sort_keys=True, default=str).encode()).hexdigest()
    if history.get("fingerprint") == fingerprint and history.get("last_outcome") in {"blocked", "no_change", "idle"}:
        unchanged = True
        six_hour_due = False
        spend_due = []
    reasons = (["manual preview/review requested"] if force else [])
    if new_incidents:
        reasons.append("new persistent failure or ownership incident")
    if spend_due:
        reasons.append("at least $100 of new unreviewed task spending")
    if six_hour_due:
        reasons.append("six-hour active-work review due")
    run_review = bool(reasons)
    notes = []
    if unknown_cost:
        notes.append("Some agent costs are unknown. Unknown is not zero; $100 triggers cannot be guaranteed for those agents until cumulative cost receipts are connected.")
    if provenance_gaps:
        notes.append("Some active agents have no registered goal mapping; ask their owners to register task purpose and evidence.")
    if unchanged:
        notes.append("The previously reviewed blocked/unchanged work state is unchanged; the timer alone does not request another LLM session.")
    if not active and not spend_due and not new_incidents:
        notes.append("No eligible active work, new spending or new incident: exit without a model call.")
    notifications = [dict(f, notification_status="proposed") for f in findings
                     if f["notify"] and f["incident_id"] not in set(history.get("notified_incidents", []))]
    return {"schema_version": 1, "generated_at": current.isoformat(),
        "mode": "advisory", "scheduler_enabled": False,
        "wake": {"eligible": run_review, "reasons": reasons,
                 "active_agent_count": len(active), "spend_due_agents": spend_due,
                 "new_incidents": new_incidents, "fingerprint": fingerprint},
        "budget": {"wake_limit_usd": "20.00", "rolling_24h_limit_usd": "80.00",
                   "wrap_up_usd": "15.00", "additional_model_cost_usd": "0.00",
                   "unknown_cost_agents": unknown_cost},
        "agents": agents, "services": services, "automations": snapshot.get("automations", []),
        "findings": findings, "proposed_notifications": notifications,
        "reflections": [reflection(a) for a in active],
        "goal_readiness": snapshot.get("goal_readiness", {
            goal: {"sim": "not established by this operational snapshot",
                   "physical": "not established by this operational snapshot"}
            for goal in sorted(GOALS)}),
        "notes": notes, "source_errors": snapshot.get("errors", []),
        "actions_executed": [], "notifications_sent": [],
        "next_event": "new work/evidence, changed dependency, new $100 spending, or a new persistent failure"}
