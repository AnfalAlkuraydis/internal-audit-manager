"""Two small Phase 1-4 held-out metrics plus inspectable component-test proof.

Only this evaluation harness reads answer labels. Production code, prompts,
datasets and labels are frozen and hashed before execution; no tuning occurs.
"""
import hashlib
import json
import time
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import sqlalchemy as sa
from dotenv import load_dotenv
from backend.config import Settings
from backend.auth import Principal
from backend.agent.orchestrator import AgentRuntime
from backend.agent.tools.contracts import ReviewDecision
from backend.database import tables as t
from backend.database.connection import create_database
from backend.database.migrate import migrate
from backend.database.repository import load_seed, read_catalog, read_bundle, create_engagement
from backend.database.schemas import Engagement
from backend.services.audit import AuditService
from scripts.run_tests import LoggedResult

ROOT=Path(__file__).resolve().parents[1]
PERIOD=("2027-02-01","2027-04-30")
CASES=(("project_governance","project"),("privileged_access","privileged_account"),("endpoint_security","device"))

def append(name,record):
    """Keep original results and append actual new evaluation evidence."""
    with (ROOT/"evaluation"/name).open("a",encoding="utf-8") as f:
        f.write(json.dumps(record,default=str)+"\n")

def rows(engine,table):
    """Read actual persisted operation records for a safe synthetic trace."""
    with engine.connect() as c:
        return [dict(r) for r in c.execute(sa.select(table)).mappings()]

def approve(service,proposal):
    """Supply a named test-human plan approval, never agent-owned authorization."""
    return service.decide(proposal["proposal_id"],ReviewDecision(
        expected_version_id=proposal["version_id"],decision="approved",
        reason="Held-out evaluation human approves the complete proposed scope."),
        Principal("heldout-evaluation-human","reviewer"))

def tool(service,name,engagement_id,**arguments):
    """Execute a real deterministic business tool with a unique test receipt."""
    return service.invoke(name,dict(engagement_id=engagement_id,operation_id=str(uuid4()),**arguments),
                          Principal("heldout-backend-test","agent"))

def frozen_inputs():
    """Fingerprint the existing application and held-out artifacts before measuring."""
    paths=sorted((ROOT/"backend").rglob("*.py"))+[
        ROOT/"data/catalog.json",ROOT/"data/held_out/dataset.json",
        ROOT/"evaluation/ground_truth/held_out.json"]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

def components(run_id,folder):
    """Rerun only the existing component suite and extract its named log entries as proof."""
    result=LoggedResult(run_id)
    suite=unittest.defaultTestLoader.discover(str(ROOT/"tests/component"),top_level_dir=str(ROOT))
    suite.run(result)
    entries=[json.loads(line) for line in (ROOT/"evaluation/component_tests.txt").read_text().splitlines()
             if line.strip()]
    actual=[entry for entry in entries if entry.get("run_id")==run_id]
    proof=dict(run_id=run_id,suite="Existing Phase 1-4 component tests",counts=result.counts,
        test_count=result.testsRun,tests=actual,
        source="evaluation/component_tests.txt",
        note="Component pass count is supporting evidence, not a third held-out metric.")
    (folder/"component_proof.json").write_text(json.dumps(proof,indent=2),encoding="utf-8")
    return proof

def control_accuracy(folder):
    """Run all existing held-out rules before comparing 36 outcomes to the frozen key."""
    engine=create_database(folder/"backend.sqlite")
    trace=[]
    try:
        migrate(engine)
        catalog=read_catalog(ROOT/"data/catalog.json")
        bundle=read_bundle(ROOT/"data/held_out/dataset.json")
        load_seed(engine,catalog,bundle)
        engagement_id="HELDOUT-BACKEND"
        create_engagement(engine,Engagement(id=engagement_id,dataset_id=bundle.dataset.id,
            department=bundle.dataset.department,period_start=PERIOD[0],period_end=PERIOD[1]))
        audit=AuditService(engine)
        plan=tool(audit,"draft_audit_plan",engagement_id,plan=dict(
            objective="Evaluate the fixed held-out population",work_program="Test the complete population for all applicable controls.",
            control_ids=[c.id for c in catalog.controls]))
        approve(audit,plan)
        actual={}
        for control in catalog.controls:
            pop=tool(audit,"get_test_population",engagement_id,control_id=control.id)
            evidence=tool(audit,"search_evidence",engagement_id,population_snapshot_id=pop["population_snapshot_id"])
            run=tool(audit,"run_control_test",engagement_id,population_snapshot_id=pop["population_snapshot_id"],
                     evidence_snapshot_id=evidence["evidence_snapshot_id"])
            trace.append(dict(control_id=control.id,population=pop,evidence=evidence,result=run))
            for row in run["results"]:actual[(control.id,row["entity_id"])]=row["outcome"]
        # Answer labels never enter AuditService, AgentRuntime, source evidence or prompts.
        key=json.loads((ROOT/"evaluation/ground_truth/held_out.json").read_text())
        expected={(r["control_id"],r["entity_id"]):r["expected_outcome"] for r in key["labels"]}
        comparison=[dict(control_id=k[0],entity_id=k[1],expected=v,actual=actual.get(k),correct=actual.get(k)==v)
                    for k,v in expected.items()]
        correct=sum(r["correct"] for r in comparison)
        result=dict(name="Held-out control-result accuracy",correct=correct,total=len(expected),
            percent=round(100*correct/len(expected),2),status="PASS" if correct==len(expected) and set(actual)==set(expected) else "FAIL",
            outcomes=dict(Counter(actual.values())),comparison=comparison)
        (folder/"control_results.json").write_text(json.dumps(dict(metric=result,trace=trace),indent=2,default=str),encoding="utf-8")
        return result
    finally:
        engine.dispose()

def agent_case(case,kind,folder,settings):
    """Observe normal real-Grok audit execution; a correct evidence wait counts as completion."""
    if settings.missing_credentials:
        return dict(case=case,status="NOT RUN",reason="Azure credentials not configured")
    engine=create_database(folder/(case+".sqlite"))
    runtime=None
    started=time.perf_counter()
    try:
        migrate(engine)
        original=read_catalog(ROOT/"data/catalog.json")
        ids={c.id for c in original.controls if c.entity_kind==kind}
        catalog=original.model_copy(update=dict(controls=[c for c in original.controls if c.id in ids],
            procedures=[p for p in original.procedures if p.control_id in ids]))
        bundle=read_bundle(ROOT/"data/held_out/dataset.json")
        load_seed(engine,catalog,bundle)
        audit=AuditService(engine)
        runtime=AgentRuntime(audit,folder/(case+"-checkpoints.sqlite"),max_calls=60)
        session_id=runtime.start(
            "Audit Digital Risk from 2027-02-01 through 2027-04-30. Test the full population "
            "for every applicable control made available in this evaluation scope. Propose confirmed "
            "findings and request missing original evidence; stop at human review or an evidence wait.",
            bundle.dataset.id)
        approvals=[];scope_plan_valid=True
        for _ in range(24):
            runtime.tick()
            session=next(r for r in rows(engine,t.agent_sessions) if r["id"]==session_id)
            pending=[p for p in audit.reviews(Principal("heldout-evaluation-human","reviewer"))
                     if p["kind"]=="plan" and p["status"]=="pending"]
            if pending:
                for p in pending:
                    if set(p["versions"][-1]["document"]["control_ids"])!=ids:
                        scope_plan_valid=False
                        break
                    approvals.append(approve(audit,p))
                if not scope_plan_valid:break
                continue
            if session["status"] in {"waiting","completed","attention_required"}:break
        calls=rows(engine,t.agent_calls)
        tasks=[w for w in rows(engine,t.work_items) if w["purpose"]=="audit"]
        with engine.connect() as c:
            latest=[audit._run_output(c,w["latest_run_id"]) for w in tasks if w["latest_run_id"]]
        actual={(run["control_id"],r["entity_id"]):r["outcome"] for run in latest for r in run["results"]}
        key=json.loads((ROOT/"evaluation/ground_truth/held_out.json").read_text())
        expected={(r["control_id"],r["entity_id"]):r["expected_outcome"] for r in key["labels"] if r["control_id"] in ids}
        proposals=rows(engine,t.proposals)
        result_rows={r["id"]:r for r in rows(engine,t.test_results)}
        finding_pairs=set()
        for proposal in proposals:
            if proposal["kind"]=="finding":
                doc=audit.reviews(Principal("heldout-evaluation-human","reviewer"),proposal["id"])["versions"][-1]["document"]
                finding_pairs.update((result_rows[i]["control_id"],result_rows[i]["entity_id"]) for i in doc["result_ids"])
        requests=rows(engine,t.evidence_requests)
        requested_entities={id for r in requests for id in r["document"]["entity_ids"]}
        checks=dict(correct_scope=scope_plan_valid and bool(approvals),
            full_population_tested=set(actual)==set(expected),
            results_match_frozen_labels=actual==expected,
            confirmed_exceptions_proposed={k for k,v in expected.items() if v=="FAIL"}<=finding_pairs,
            missing_evidence_requested={k[1] for k,v in expected.items() if v=="MISSING_EVIDENCE"}<=requested_entities,
            valid_tool_arguments=bool(calls) and all(c["schema_valid"] for c in calls),
            no_self_approval=all(d["reviewer_role"]!="agent" for d in rows(engine,t.review_decisions)),
            appropriate_stop=session["status"] in {"waiting","completed"})
        report=dict(case=case,status="PASS" if all(checks.values()) else "FAIL",checks=checks,
            execution_date_utc=datetime.now(timezone.utc).isoformat(),session_status=session["status"],
            error_code=session["error_code"],tool_calls=len(calls),failed_tool_calls=sum(not c["success"] for c in calls),
            duration_seconds=round(time.perf_counter()-started,3))
        trace=dict(report=report,inferences=rows(engine,t.agent_inferences),tool_calls=calls,
            results=rows(engine,t.test_results),requests=requests,proposals=rows(engine,t.proposals),
            versions=rows(engine,t.proposal_versions),decisions=rows(engine,t.review_decisions),
            activity=rows(engine,t.activity))
        (folder/(case+"-trace.json")).write_text(json.dumps(trace,indent=2,default=str),encoding="utf-8")
        return report
    finally:
        if runtime:runtime.close()
        engine.dispose()

def main():
    """Execute a fixed small suite once, preserve all outcomes and publish just two metrics."""
    load_dotenv(ROOT/".env")
    settings=Settings.from_env()
    run_id=str(uuid4())
    folder=ROOT/"evaluation/heldout_runs"/run_id
    folder.mkdir(parents=True)
    frozen=frozen_inputs()
    protocol=dict(run_id=run_id,execution_date_utc=datetime.now(timezone.utc).isoformat(),
        cases=[c for c,_ in CASES],period=PERIOD,frozen_inputs=frozen,
        stop_rule="Finish all available control tests, propose confirmed findings and request missing evidence; human findings/closure remain pending.",
        exclusions="No stress, adversarial, Gmail or standalone-prototype tests. No prompt/data/label tuning or selective reruns.",
        note="Small pre-existing synthetic held-out partition; expected labels are provisional, not human-validated.")
    (folder/"protocol.json").write_text(json.dumps(protocol,indent=2),encoding="utf-8")
    proof=components(run_id,folder)
    accuracy=control_accuracy(folder)
    print(json.dumps(dict(metric=accuracy["name"],correct=accuracy["correct"],total=accuracy["total"],status=accuracy["status"])),flush=True)
    cases=[]
    for case,kind in CASES:
        try:report=agent_case(case,kind,folder,settings)
        except Exception as error:report=dict(case=case,status="FAIL",error_code=getattr(error,"code",type(error).__name__))
        cases.append(report)
        append("live_agent_tests.txt",dict(event="heldout_case",run_id=run_id,**report))
        print(json.dumps(report),flush=True)
    completion=dict(name="Held-out real-agent task completion",passed=sum(c["status"]=="PASS" for c in cases),
        total=len(cases),not_run=sum(c["status"]=="NOT RUN" for c in cases),
        percent=round(100*sum(c["status"]=="PASS" for c in cases)/len(cases),2),cases=cases)
    unchanged=frozen_inputs()==frozen
    summary=dict(run_id=run_id,event="minimal_phase1_to_phase4_heldout",metrics=[accuracy,completion],
        component_proof=dict(counts=proof["counts"],test_count=proof["test_count"],path=str((folder/"component_proof.json").relative_to(ROOT))),
        artifact_directory=str(folder.relative_to(ROOT)),production_and_evaluation_inputs_unchanged=unchanged,
        cost=None,note=protocol["note"])
    (folder/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    (ROOT/"evaluation/heldout_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    append("metrics_summary.txt",summary)
    append("regression_history.txt",dict(run_id=run_id,event="heldout_evaluation_completed",
        control_results=accuracy["status"],agent_case_statuses={c["case"]:c["status"] for c in cases},
        production_and_evaluation_inputs_unchanged=unchanged,artifact_directory=summary["artifact_directory"]))
    print(json.dumps(dict(run_id=run_id,component_tests=proof["counts"],unchanged=unchanged,
        agent_passed=completion["passed"],agent_total=completion["total"])),flush=True)
    return 0 if accuracy["status"]=="PASS" and completion["passed"]==len(cases) and unchanged and proof["counts"]["FAIL"]==0 else 1

if __name__=="__main__":
    raise SystemExit(main())
