"""Explicit synthetic email previews for the connected workspace, never automatic ingestion.

Preview generation reads real request scope but writes no evidence, sends no mail,
and grants no approval. A human must submit the normalized preview through MailService.
"""
from datetime import date, timedelta
from uuid import uuid4
import sqlalchemy as sa
from backend.database import tables as t
from backend.email.models import IncomingMail
from backend.services.control_testing import required_kinds
from backend.services.errors import AuditError

def sample_reply(audit, request_id, now):
    """Prepare clearly synthetic facts inside the actual outstanding request's scope."""
    with audit.engine.connect() as c:
        request=audit._row(c,t.evidence_requests,request_id)
        if request["status"] in {"resolved","cancelled","waiting_for_approval"}:
            raise AuditError("request_not_ready_for_reply")
        outgoing=c.execute(sa.select(t.mail_outbox).join(t.simulated_deliveries,
            t.simulated_deliveries.c.outbox_id==t.mail_outbox.c.id).where(
            t.mail_outbox.c.request_id==request_id).order_by(t.mail_outbox.c.created_at)).mappings().first()
        if not outgoing:
            raise AuditError("request_not_delivered")
        doc=request["document"]
        snapshot=audit._artifact(c,doc["evidence_snapshot_id"],request["engagement_id"],"evidence")["payload"]
        pop=audit._current_population(c,request["engagement_id"],snapshot["population_snapshot_id"])
        message=dict(message_id="synthetic-"+str(uuid4()),in_reply_to=outgoing["message_id"],
            sender=doc["recipient"],body="SYNTHETIC EMAIL: sample department reply submitted by the auditor.")
        purpose=doc.get("purpose","evidence")
        if purpose=="action_plan":
            _,finding=audit._approved(c,doc["finding_id"],"finding")
            message["action_plan"]=dict(owner="Synthetic department process owner",
                action=finding["document"]["recommendation"],due_on=(now.date()+timedelta(days=14)).isoformat())
        else:
            members=[e for e in pop["members"] if e["id"] in doc["entity_ids"]]
            if purpose=="implementation":
                engagement=audit._row(c,t.engagements,request["engagement_id"])
                plan=audit._plan(c,request["engagement_id"])
                start=engagement["period_end"]+timedelta(days=1)
                end=start+timedelta(days=min(29,plan["document"]["verification_window_days"]-1))
                audit._verification_scope(c,engagement,plan,doc["finding_id"],pop["control"]["id"],start,end)
                if not members:raise AuditError("request_population_empty")
                entity={**members[0],"id":"SYN-"+str(uuid4()),"name":"Synthetic follow-up verification record",
                    "active_from":start.isoformat(),"active_to":None}
                entity.pop("dataset_id",None)
                if entity["kind"]=="project":
                    deployed=start+timedelta(days=min(2,(end-start).days))
                    entity.update(active_from=deployed.isoformat(),active_to=deployed.isoformat(),
                                  facts={"deployed_on":deployed.isoformat()})
                message["entities"]=[entity]
                message["verification_period"]=dict(period_start=start.isoformat(),period_end=end.isoformat())
                members=[entity]
            sources=[dict(r) for r in c.execute(sa.select(t.sources)).mappings()]
            records=[]
            for entity in members:
                kinds=required_kinds(pop["procedure"]["rule"])
                if purpose=="implementation":
                    # New verification records carry a complete baseline for their entity kind.
                    rules=c.execute(sa.select(t.procedures.c.rule).join(t.controls,
                        t.controls.c.id==t.procedures.c.control_id).where(
                        t.controls.c.entity_kind==entity["kind"])).scalars().all()
                    kinds=sorted({k for rule in rules for k in required_kinds(rule)})
                if purpose=="evidence":
                    gaps={g["evidence_kind"] for g in snapshot["gaps"] if g["entity_id"]==entity["id"]}
                    if not gaps:raise AuditError("sample_requires_missing_evidence_use_manual_reply")
                    kinds=[k for k in kinds if k in gaps]
                for kind in kinds:
                    source=next((s for s in sources if kind in s["allowed_kinds"] and
                        s["authority"]==("secondary" if kind=="grc_approval" else "original")),None)
                    if not source:raise AuditError("sample_source_not_available")
                    as_of=(date.fromisoformat(entity["facts"]["deployed_on"]) if entity["kind"]=="project" else
                        (end if purpose=="implementation" else date.fromisoformat(pop["execution_scope"]["period_end"])))
                    if entity["kind"]!="project" and entity.get("active_to"):
                        as_of=min(as_of,date.fromisoformat(entity["active_to"]))
                    when=(start if purpose=="implementation" and entity["kind"]=="project" else as_of)
                    if kind in {"project_approval","grc_approval"}:
                        when=when if purpose=="implementation" else as_of+timedelta(days=2)
                        facts={"approved_on":when.isoformat()}
                    elif kind=="risk_assessment":facts={"assessed_on":when.isoformat()}
                    elif kind=="employment":facts={"employment_end":None}
                    elif kind in {"mfa","encryption"}:facts={"enabled":True,"snapshot_on":as_of.isoformat()}
                    elif kind=="edr":facts={"covered":True,"snapshot_on":as_of.isoformat()}
                    elif kind=="access_review":facts={"reviewed_on":as_of.isoformat()}
                    else:facts={"scanned_on":as_of.isoformat()}
                    records.append(dict(id="SYN-EV-"+str(uuid4()),entity_id=entity["id"],source_id=source["id"],
                        source_record_id="SYN-SRC-"+str(uuid4()),kind=kind,version=1,
                        observed_on=when.isoformat(),captured_on=max(now.date(),when).isoformat(),facts=facts))
            message["evidence"]=records
        return dict(notice="Synthetic preview only. Review before submitting; normal validation and approvals still apply.",
                    message=IncomingMail.model_validate(message).model_dump(mode="json"))
