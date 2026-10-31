"""Opt-in actual Azure Grok autonomy evaluation; no scripted model/tool selections.

The driver supplies synthetic source conditions and explicit test-human approvals.
Grok chooses every business tool and its arguments. All receipts and usage are saved.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import sqlalchemy as sa
from dotenv import load_dotenv
from backend.config import Settings
from backend.agent.orchestrator import AgentRuntime
from backend.auth import Principal
from backend.database import tables as t
from backend.database.connection import create_database
from backend.database.migrate import migrate
from backend.database.repository import load_seed
from backend.database.schemas import Catalog, SeedBundle
from backend.services.audit import AuditService
from backend.services.errors import AuditError
from backend.agent.tools.contracts import ReviewDecision
from backend.email.models import IncomingMail

ROOT = Path(__file__).resolve().parents[1]
CASES = ("complete", "alternate_source", "missing_department", "contradictory", "resume_and_closure", "tool_error_recovery", "full_population")

class FaultService(AuditService):
    """Inject exactly one recoverable source error; the real model must decide recovery."""
    def __init__(self, engine, fault=False):
        """Keep normal safeguards and record whether the injected failure was exercised."""
        super().__init__(engine)
        self.fault, self.triggered = fault, False

    def invoke(self, name, arguments, actor):
        """Expose a safe, transient business-tool error once during evidence retrieval."""
        if self.fault and not self.triggered and name == "search_evidence":
            self.triggered = True
            raise AuditError("source_temporarily_unavailable")
        return super().invoke(name, arguments, actor)

def read_rows(engine, table):
    """Serialize actual persisted records for an inspectable trace."""
    with engine.connect() as c:
        return [dict(r) for r in c.execute(sa.select(table)).mappings()]

def seed(engine, case):
    """Create a small independent development case without loading held-out labels."""
    catalog = json.loads((ROOT/"data/catalog.json").read_text())
    catalog["controls"] = [c for c in catalog["controls"] if case=="full_population" or c["id"]=="PR-02.v1"]
    catalog["procedures"] = [c for c in catalog["procedures"] if case=="full_population" or c["control_id"]=="PR-02.v1"]
    bundle = json.loads((ROOT/"data/development/dataset.json").read_text())
    target = "PRJ-003" if case in {"missing_department", "resume_and_closure"} else "PRJ-001"
    bundle["entities"] = [e for e in bundle["entities"] if case=="full_population" or e["id"]==target]
    bundle["evidence"] = [e for e in bundle["evidence"] if case=="full_population" or e["entity_id"]==target]
    if case == "alternate_source":
        catalog["sources"].append(dict(id="approval_archive", system="Authorized original approval archive",
            authority="original", allowed_kinds=["project_approval"]))
        for e in bundle["evidence"]:
            if e["kind"]=="project_approval":
                e["source_id"]="approval_archive"
    if case == "contradictory":
        original = next(e for e in bundle["evidence"] if e["kind"]=="project_approval")
        bundle["evidence"].append({**original, "id":"CONFLICT-APPROVAL",
            "source_record_id":"CONFLICT-RECORD", "facts":{"approved_on":"2026-01-02"}})
    load_seed(engine, Catalog.model_validate(catalog), SeedBundle.model_validate(bundle))
    return bundle["dataset"]["id"]

def approve(audit, proposal):
    """Act as a clearly identified evaluation human, never as the autonomous agent."""
    audit.decide(proposal["proposal_id"], ReviewDecision(expected_version_id=proposal["version_id"],
        decision="approved", reason="Explicit evaluation-human approval"), Principal("evaluation-human","reviewer"))

def run_case(case, directory, resume=False):
    """Drive backend ticks and external events; assert observable completion conditions."""
    started=time.perf_counter()
    engine=create_database(directory/"audit.sqlite")
    migrate(engine)
    dataset=seed(engine,case) if not resume else None
    audit=FaultService(engine,case=="tool_error_recovery")
    checkpoint=directory/"checkpoints.sqlite"
    runtime=AgentRuntime(audit,checkpoint,max_calls=70)
    if resume:
        session_id=read_rows(engine,t.agent_sessions)[0]["id"]
        with engine.begin() as c:
            c.execute(t.agent_sessions.update().where(t.agent_sessions.c.id==session_id).values(
                status="queued",wake_version=t.agent_sessions.c.wake_version+1,error_code=None))
    else:
        session_id=runtime.start("Audit Digital Risk for 2026-01-01 through 2026-08-31. "
            "Test all applicable controls and follow approved findings through independent remediation.",dataset)
    replies=set(); approvals=[]; restarted=resume; error=None
    if resume:
        approvals=[dict(kind=p["kind"],id=p["proposal_id"],reused_prior_decision=True)
            for p in audit.reviews(Principal("evaluation-human","reviewer")) if p["status"]=="approved"]
    try:
        for iteration in range(38):
            runtime.tick()
            session=next(r for r in read_rows(engine,t.agent_sessions) if r["id"]==session_id)
            if session["status"]=="attention_required":
                error=session["error_code"]; break
            reviews=audit.reviews(Principal("evaluation-human","reviewer"))
            for proposal in reviews:
                if proposal["status"]=="pending" and (proposal["kind"]=="plan" or
                        (case=="resume_and_closure" and proposal["kind"] in {"finding","closure"})):
                    approve(audit,proposal); approvals.append(dict(kind=proposal["kind"],id=proposal["proposal_id"]))
            requests=read_rows(engine,t.evidence_requests)
            if case=="resume_and_closure":
                for request in requests:
                    if request["id"] in replies or request["status"] not in {"sent","received"}:
                        continue
                    outgoing=next((m for m in read_rows(engine,t.mail_outbox)
                        if m["request_id"]==request["id"] and m["status"]=="delivered"),None)
                    if not outgoing: continue
                    if not restarted:
                        runtime.close()
                        runtime=AgentRuntime(audit,checkpoint,max_calls=70)
                        restarted=True
                    purpose=request["document"].get("purpose","evidence")
                    fixtures=json.loads((ROOT/"tests/fixtures/followup_messages.json").read_text())["messages"]
                    fixture=fixtures[{"evidence":0,"action_plan":1,"implementation":2}[purpose]]
                    fields={k:fixture[k] for k in ("evidence","entities","action_plan","verification_period") if k in fixture}
                    receipt=runtime.mail.receive(IncomingMail(
                        message_id="evaluation-"+request["id"],in_reply_to=outgoing["message_id"],
                        sender=request["document"]["recipient"],body="Synthetic department reply",**fields))
                    if receipt["status"]!="resolved":
                        raise AssertionError("Reply failed validation: "+receipt["validation_code"])
                    replies.add(request["id"])
            if session["status"] in {"waiting","completed"}:
                if case in {"missing_department","contradictory","full_population"} and requests: break
                if case not in {"missing_department","contradictory","resume_and_closure"} and session["status"]=="completed": break
                if case=="resume_and_closure" and session["status"]=="completed": break
        calls=read_rows(engine,t.agent_calls)
        results=read_rows(engine,t.test_results)
        proposals=read_rows(engine,t.proposals)
        requests=read_rows(engine,t.evidence_requests)
        outcomes=[r["outcome"] for r in results]
        checks={"no_runtime_error":error is None,"all_arguments_schema_valid":all(c["schema_valid"] for c in calls),
                "tools_exercised":bool(calls),"human_plan_gate":any(a["kind"]=="plan" for a in approvals)}
        if case in {"complete","alternate_source","tool_error_recovery"}:
            checks.update(completed=session["status"]=="completed",pass_saved="PASS" in outcomes,no_unnecessary_email=not requests)
        if case=="alternate_source":
            evidence=read_rows(engine,t.artifacts)
            checks["alternate_original_used"]=any(a["kind"]=="evidence" and any(
                r["source_id"]=="approval_archive" for r in a["payload"]["records"]) for a in evidence)
        if case=="tool_error_recovery":
            checks["error_exercised_and_recovered"]=audit.triggered and any(not c["success"] for c in calls) and "PASS" in outcomes
        if case in {"missing_department","contradictory"}:
            expected="MISSING_EVIDENCE" if case=="missing_department" else "CONTRADICTORY_EVIDENCE"
            checks.update(correct_blocked_outcome=expected in outcomes,department_requested=bool(requests),
                no_guessed_finding=not any(p["kind"]=="finding" for p in proposals))
        if case=="full_population":
            controls={r["control_id"] for r in results}
            tasks=read_rows(engine,t.work_items)
            checks.update(all_nine_controls_tested=len(controls)==9,
                independent_work_continued=any(w["state"]=="blocked" for w in tasks)
                    and sum(w["state"]=="completed" for w in tasks)==7,
                all_72_pairs_tested=len({(r["control_id"],r["entity_id"]) for r in results})==72,
                confirmed_findings_proposed=any(p["kind"]=="finding" for p in proposals),
                department_requested=bool(requests))
        if case=="resume_and_closure":
            with engine.connect() as c:
                findings=[p for p in proposals if p["kind"]=="finding"]
                closed=bool(findings) and all(audit._is_closed(c,p["id"]) for p in findings)
            checks.update(restarted=restarted,original_failure_preserved="FAIL" in outcomes,
                closure_human_approved=closed,three_reply_types=len(replies)==3,completed=session["status"]=="completed")
        report=dict(case=case,status="PASS" if all(checks.values()) else "FAIL",checks=checks,
            session_status=session["status"],error_code=error,tool_calls=len(calls),
            failed_tool_calls=sum(not c["success"] for c in calls),
            duration_seconds=time.perf_counter()-started,human_decisions=approvals)
        inferences=read_rows(engine,t.agent_inferences)
        report["inference_calls"]=len(inferences)
        report["input_tokens"]=sum((r["response"]["usage"]["input_tokens"] or 0) for r in inferences)
        report["output_tokens"]=sum((r["response"]["usage"]["output_tokens"] or 0) for r in inferences)
        report["api_cost"]=None
        trace=dict(report=report,inferences=inferences,tool_calls=calls,results=results,
            requests=requests,inbox=read_rows(engine,t.mail_inbox),outbox=read_rows(engine,t.mail_outbox),
            activity=read_rows(engine,t.activity))
        archive=ROOT/"evaluation"/"phase4_traces"/directory.parent.name
        archive.mkdir(parents=True,exist_ok=True)
        trace_path=archive/(case+"-"+str(uuid4())+".json")
        report["trace_path"]=str(trace_path.relative_to(ROOT))
        trace_path.write_text(json.dumps(trace,default=str,indent=2),encoding="utf-8")
        return report
    finally:
        runtime.close(); engine.dispose()

def main():
    """Run requested live cases, saving failures and honest NOT RUN configuration outcomes."""
    parser=argparse.ArgumentParser()
    parser.add_argument("--case",choices=CASES,action="append")
    parser.add_argument("--resume-directory",type=Path)
    args=parser.parse_args()
    if args.resume_directory and len(args.case or [])!=1:
        parser.error("Resume requires exactly one --case")
    load_dotenv(ROOT/".env")
    settings=Settings.from_env()
    run_id=str(uuid4()); results=[]
    destination=ROOT/"var"/"phase4-evaluation"/run_id
    destination.mkdir(parents=True)
    for case in args.case or CASES:
        folder=args.resume_directory.resolve() if args.resume_directory else destination/case
        folder.mkdir(exist_ok=True)
        if settings.missing_credentials:
            result=dict(case=case,status="NOT RUN",reason="missing_azure_configuration")
        else:
            try: result=run_case(case,folder,resume=bool(args.resume_directory))
            except Exception as error:
                result=dict(case=case,status="FAIL",error_code=getattr(error,"code",type(error).__name__))
        results.append(result); print(json.dumps(result),flush=True)
        with (ROOT/"evaluation"/"live_agent_tests.txt").open("a",encoding="utf-8") as f:
            f.write(json.dumps(dict(run_id=run_id,execution_date_utc=datetime.now(timezone.utc).isoformat(),
                execution_mode="live",inference_source="azure_grok",test_version="phase4-v1",
                event="phase4_autonomy_case",**({"trace_path":str(folder/"trace.json")} if "trace_path" not in result else {}),**result))+"\n")
    summary=dict(run_id=run_id,event="phase4_real_autonomy",results=results,
        api_cost=None,trace_directory=str(destination),held_out_performance="NOT RUN")
    with (ROOT/"evaluation"/"metrics_summary.txt").open("a",encoding="utf-8") as f:
        f.write(json.dumps(summary)+"\n")
    (destination/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    raise SystemExit(0 if all(r["status"]=="PASS" for r in results) else 1)

if __name__=="__main__":
    main()
