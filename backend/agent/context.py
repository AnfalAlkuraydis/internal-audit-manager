"""Build factual current-work context; the model still chooses its next permitted action."""
import sqlalchemy as sa
from fastapi.encoders import jsonable_encoder
from backend.database import tables as t
from backend.database.repository import fingerprint
from backend.services.activity import stamp
from backend.services.errors import AuditError
from backend.services.control_testing import required_kinds

def observe(audit, engagement_id, now):
    """Read current approvals/work and refresh task records without selecting a tool sequence."""
    with audit.engine.begin() as c:
        engagement = audit._row(c, t.engagements, engagement_id)
        roots = [dict(r) for r in c.execute(sa.select(t.proposals).where(
            t.proposals.c.engagement_id == engagement_id)).mappings()]
        proposals = []
        for root in roots:
            _, version, decision = audit._latest(c, root["id"])
            if root["kind"] == "escalation" and version["document"].get("overdue_request_id"):
                tracking = c.execute(sa.select(t.mail_followups).where(
                    t.mail_followups.c.request_id == version["document"]["overdue_request_id"])).mappings().first()
                if not tracking or tracking["state"] != "waiting" or tracking["escalation_proposal_id"] != root["id"]:
                    continue
            proposals.append({**audit._proposal_output(c, root["id"]), "document": version["document"],
                              "review_feedback": decision["reason"] if decision else None})
        plans = [p for p in proposals if p["kind"] == "plan"]
        plan = plans[0] if plans else None
        if plan and plan["status"] == "approved":
            for control_id in plan["document"]["control_ids"]:
                key = fingerprint([engagement_id, plan["version_id"], control_id, "audit"])
                if not c.execute(sa.select(t.work_items.c.id).where(t.work_items.c.id == key)).first():
                    c.execute(t.work_items.insert().values(id=key, engagement_id=engagement_id,
                        plan_version_id=plan["version_id"], control_id=control_id, purpose="audit",
                        finding_id=None, state="ready", latest_run_id=None, updated_at=stamp(now)))
        current_tasks = []
        if plan and plan["status"] == "approved":
            current_tasks = [dict(r) for r in c.execute(sa.select(t.work_items).where(
                t.work_items.c.engagement_id == engagement_id,
                t.work_items.c.plan_version_id == plan["version_id"])).mappings()]
        artifacts = [dict(r) for r in c.execute(sa.select(t.artifacts).where(
            t.artifacts.c.engagement_id == engagement_id).order_by(t.artifacts.c.created_at.desc())).mappings()]
        references = []
        seen = set()
        for row in artifacts:
            payload = row["payload"]
            control_id = payload.get("control_id", payload.get("control", {}).get("id"))
            key = (row["kind"], control_id, payload.get("finding_id") or payload.get("verification_for_finding_id"))
            if key in seen:
                continue
            seen.add(key)
            item = dict(id=row["id"], kind=row["kind"], control_id=control_id)
            if row["kind"] == "run":
                item.update(audit._run_output(c, row["id"]))
                item["population_snapshot_id"] = payload["population_snapshot_id"]
                item["evidence_snapshot_id"] = payload["evidence_snapshot_id"]
            elif row["kind"] == "evidence":
                item.update(population_snapshot_id=payload["population_snapshot_id"], gaps=payload["gaps"])
            references.append(item)
        requests = []
        for row in c.execute(sa.select(t.evidence_requests).where(
                t.evidence_requests.c.engagement_id == engagement_id)).mappings():
            followup = c.execute(sa.select(t.mail_followups).where(
                t.mail_followups.c.request_id == row["id"])).mappings().first()
            snapshot = audit._artifact(c,row["document"]["evidence_snapshot_id"],engagement_id,"evidence")["payload"]
            population = audit._artifact(c,snapshot["population_snapshot_id"],engagement_id,"population")["payload"]
            kinds = sorted({g["evidence_kind"] for g in snapshot["gaps"] if g["entity_id"] in row["document"]["entity_ids"]}
                or set(required_kinds(population["procedure"]["rule"])))
            requests.append(dict(id=row["id"], status=row["status"], evidence_kinds=kinds, document=row["document"],
                                 followup=dict(followup) if followup else None))
        inbox = [dict(r) for r in c.execute(sa.select(t.mail_inbox).join(
            t.evidence_requests, t.mail_inbox.c.request_id == t.evidence_requests.c.id).where(
            t.evidence_requests.c.engagement_id == engagement_id).order_by(
            t.mail_inbox.c.received_at.desc()).limit(8)).mappings()]
        approved_findings = []
        covered = set()
        covered_pairs = set()
        for proposal in proposals:
            if proposal["kind"] != "finding":
                continue
            covered.update(proposal["document"]["result_ids"])
            for result_id in proposal["document"]["result_ids"]:
                item = audit._row(c, t.test_results, result_id)
                covered_pairs.add((item["control_id"], item["entity_id"]))
            if proposal["status"] == "approved":
                approved_findings.append({**proposal,
                    "action_plan": audit._action_plan(c, proposal["proposal_id"]),
                    "closed": audit._is_closed(c, proposal["proposal_id"])})
        uncovered = [r["id"] for ref in references if ref["kind"] == "run" and ref.get("purpose") == "audit"
                     for r in ref["results"] if r["outcome"] == "FAIL" and r["id"] not in covered
                     and (ref["control_id"], r["entity_id"]) not in covered_pairs]
        needs = []
        if not plan:
            needs.append("retrieve_requirements_and_propose_work_program")
        elif plan["status"] == "changes_requested":
            needs.append("revise_returned_work_program")
        if plan and plan["status"] == "approved":
            if any(task["state"] == "ready" for task in current_tasks):
                needs.append("independent_audit_work_ready")
            for task in current_tasks:
                if task["state"] != "blocked":
                    continue
                run = audit._artifact(c,task["latest_run_id"],engagement_id,"run")["payload"]
                snapshot = audit._artifact(c,run["evidence_snapshot_id"],engagement_id,"evidence")["payload"]
                population = audit._artifact(c,run["population_snapshot_id"],engagement_id,"population")["payload"]
                bad = {r["entity_id"] for r in audit._run_output(c,task["latest_run_id"])["results"]
                    if r["outcome"] in {"MISSING_EVIDENCE","CONTRADICTORY_EVIDENCE","ERROR"}}
                kinds = {g["evidence_kind"] for g in snapshot["gaps"] if g["entity_id"] in bad} or set(
                    required_kinds(population["procedure"]["rule"]))
                covered_request = any(r["status"] not in {"resolved","cancelled"}
                    and r["document"].get("purpose","evidence") == "evidence"
                    and bad <= set(r["document"]["entity_ids"])
                    and kinds <= set(r["evidence_kinds"]) for r in requests)
                if not covered_request:
                    needs.append("unresolved_evidence_obligation:" + task["control_id"])
            if uncovered:
                needs.append("unreviewed_confirmed_exceptions")
            for finding in approved_findings:
                if finding["closed"]:
                    continue
                purpose = "action_plan" if not finding["action_plan"] else "implementation"
                outstanding = any(r["document"].get("finding_id") == finding["proposal_id"]
                                  and r["document"].get("purpose", "evidence") == purpose
                                  and r["status"] not in {"resolved", "cancelled"} for r in requests)
                closures = [p for p in proposals if p["kind"] == "closure"
                            and p["document"]["finding_id"] == finding["proposal_id"]]
                if not outstanding and not closures:
                    needs.append("follow_up_approved_finding:" + finding["proposal_id"])
        returned = [p for p in proposals if p["status"] == "changes_requested"]
        for proposal in returned:
            if proposal["kind"] in {"finding","closure"}:
                needs.append("revise_returned_proposal:" + proposal["kind"] + ":" + proposal["proposal_id"])
        pending = [p for p in proposals if p["status"] == "pending"]
        blocked = [task for task in current_tasks if task["state"] == "blocked"]
        wait = bool(pending or returned or blocked or any(not f["closed"] for f in approved_findings)
                    or (plan and plan["status"] in {"rejected", "changes_requested"}))
        return jsonable_encoder(dict(scope=engagement, plan=plan, work_items=current_tasks,
            proposals=proposals, approved_findings=approved_findings, latest_artifacts=references,
            uncovered_failed_result_ids=uncovered, evidence_requests=requests,
            incoming_messages=inbox, authorized_recipients=audit.contacts.get(engagement["department"], []),
            needs=needs, waiting=wait, pending_plan=bool(plan and plan["status"] == "pending"),
            backend_time=stamp(now)))

def update_work(audit, engagement_id, run_id, now):
    """Persist actual run progress separately for audit execution and remediation."""
    with audit.engine.begin() as c:
        run = audit._artifact(c, run_id, engagement_id, "run")["payload"]
        population = audit._artifact(c, run["population_snapshot_id"], engagement_id, "population")["payload"]
        result = audit._run_output(c, run_id)
        blocked = any(result["counts"][status] for status in (
            "MISSING_EVIDENCE", "CONTRADICTORY_EVIDENCE", "ERROR"))
        key = fingerprint([engagement_id, population["plan_version_id"], result["control_id"],
                           result["purpose"], run.get("finding_id")])
        if result["purpose"] == "audit":
            key = fingerprint([engagement_id, population["plan_version_id"], result["control_id"], "audit"])
        row = dict(id=key, engagement_id=engagement_id, plan_version_id=population["plan_version_id"],
            control_id=result["control_id"], purpose=result["purpose"], finding_id=run.get("finding_id"),
            state="blocked" if blocked else "completed", latest_run_id=run_id, updated_at=stamp(now))
        if c.execute(sa.select(t.work_items.c.id).where(t.work_items.c.id == key)).first():
            c.execute(t.work_items.update().where(t.work_items.c.id == key).values(**row))
        else:
            c.execute(t.work_items.insert().values(**row))
