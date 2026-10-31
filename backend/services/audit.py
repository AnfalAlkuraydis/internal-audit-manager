"""Execute eight tools and enforce human review boundaries in one local service.

All business writes and retry receipts share a transaction. Evidence and
calculated artifacts are immutable; edits create proposal versions instead.
There is no model loop, email sender, or autonomous approval in this module.
"""
import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4
import sqlalchemy as sa
from fastapi.encoders import jsonable_encoder
from backend.auth import Principal, require_role
from backend.database import tables as t
from backend.database.repository import fingerprint
from backend.agent.tools.contracts import (
    CONTRACTS, OUTCOMES, PlanDocument, FindingDocument, ProposalOutput,
    DraftEdit, ReviewDecision, ActionPlanInput,
)
from backend.services.control_testing import evaluate, required_kinds, scope_date
from backend.services.errors import AuditError

ROOT = Path(__file__).resolve().parents[2]

def uid() -> str:
    """Generate stable record identities independent of synthetic fixture IDs."""
    return str(uuid4())

def timestamp() -> str:
    """Record event time explicitly in UTC."""
    return datetime.now(timezone.utc).isoformat()

class AuditService:
    """Shared deterministic backend used by tools and human-only review routes."""

    def __init__(self, engine, contacts: dict | None = None):
        """Accept an explicit database engine and optional department routing configuration."""
        self.engine = engine
        self.contacts = contacts if contacts is not None else json.loads(
            (ROOT / "data/department_contacts.json").read_text(encoding="utf-8"))

        if (not isinstance(self.contacts, dict) or any(
                not isinstance(department, str) or not isinstance(recipients, list)
                or any(not isinstance(address, str) or not address for address in recipients)
                for department, recipients in self.contacts.items())):
            raise AuditError("invalid_department_contacts", 503)

    def _row(self, c, table, id):
        """Read a required record or return a safe not-found error."""
        row = c.execute(sa.select(table).where(table.c.id == id)).mappings().first()
        if row is None:
            raise AuditError("record_not_found", 404)
        return dict(row)

    def _event(self, c, engagement_id, actor, event, record_id):
        """Append identity and time without copying prompts or credentials into history."""
        c.execute(t.audit_events.insert().values(
            id=uid(), engagement_id=engagement_id, actor_id=actor.id,
            actor_role=actor.role, event=event, record_id=record_id, created_at=timestamp()))

    def _latest(self, c, proposal_id):
        """Return a proposal and its current version; old approvals never authorize new edits."""
        root = self._row(c, t.proposals, proposal_id)
        version = c.execute(sa.select(t.proposal_versions).where(
            t.proposal_versions.c.proposal_id == proposal_id).order_by(
            t.proposal_versions.c.version.desc())).mappings().first()
        if version is None:
            raise AuditError("proposal_has_no_version")
        decision = c.execute(sa.select(t.review_decisions).where(
            t.review_decisions.c.version_id == version["id"])).mappings().first()
        return root, dict(version), dict(decision) if decision else None

    def _proposal_output(self, c, proposal_id):
        """Expose the exact version and decision state a reviewer must open."""
        root, version, decision = self._latest(c, proposal_id)
        return ProposalOutput(proposal_id=root["id"], version_id=version["id"],
                              version=version["version"], kind=root["kind"],
                              status=decision["decision"] if decision else "pending").model_dump()

    def _approved(self, c, proposal_id, kind):
        """Require approval of the latest version and verify the proposal type."""
        root, version, decision = self._latest(c, proposal_id)
        if root["kind"] != kind or not decision or decision["decision"] != "approved":
            raise AuditError(kind + "_approval_required", 403)
        return root, version

    def _plan(self, c, engagement_id):
        """Locate the engagement's currently approved work program."""
        root = c.execute(sa.select(t.proposals).where(
            t.proposals.c.engagement_id == engagement_id, t.proposals.c.kind == "plan")).mappings().first()
        if not root:
            raise AuditError("plan_approval_required", 403)
        return self._approved(c, root["id"], "plan")[1]

    def _artifact(self, c, id, engagement_id, kind):
        """Reject foreign, mismatched or corrupted snapshots before using them."""
        row = self._row(c, t.artifacts, id)
        if row["engagement_id"] != engagement_id or row["kind"] != kind:
            raise AuditError("artifact_scope_mismatch", 403)
        if row["digest"] != fingerprint({"engagement_id": engagement_id, "kind": kind, "payload": row["payload"]}):
            raise AuditError("artifact_integrity_error")
        return row

    def _save_artifact(self, c, engagement_id, kind, payload):
        """Reuse identical frozen inputs instead of duplicating business artifacts."""
        payload = jsonable_encoder(payload)
        digest = fingerprint({"engagement_id": engagement_id, "kind": kind, "payload": payload})
        existing = c.execute(sa.select(t.artifacts).where(t.artifacts.c.digest == digest)).mappings().first()
        if existing:
            return existing["id"], False
        id = uid()
        c.execute(t.artifacts.insert().values(id=id, engagement_id=engagement_id, kind=kind,
                                            digest=digest, payload=payload, created_at=timestamp()))
        return id, True

    def _requirements(self, c, engagement):
        """Join applicable policy/control/procedure records using the actual audit scope."""
        controls = c.execute(sa.select(t.controls).join(t.policies).where(
            t.policies.c.department == engagement["department"],
            t.policies.c.effective_from <= engagement["period_end"],
            sa.or_(t.policies.c.effective_to.is_(None),
                   t.policies.c.effective_to >= engagement["period_start"]))).mappings().all()
        result = []
        for control in controls:
            policy = self._row(c, t.policies, control["policy_id"])
            procedure = c.execute(sa.select(t.procedures).where(
                t.procedures.c.control_id == control["id"])).mappings().one()
            result.append(dict(control_id=control["id"], title=control["title"],
                requirement=control["requirement"], policy_id=policy["id"], policy_version=policy["version"],
                policy_text=policy["text"], procedure_id=procedure["id"],
                procedure_version=procedure["version"], rule=procedure["rule"]))
        return sorted(result, key=lambda item: item["control_id"])

    def _validate_plan(self, c, engagement, document):
        """Require applicable control IDs; follow-up plans must target an approved finding."""
        plan = PlanDocument.model_validate(document)
        allowed = {item["control_id"] for item in self._requirements(c, engagement)}
        if not set(plan.control_ids) <= allowed:
            raise AuditError("control_outside_scope")
        if plan.remediation_for_finding_id:
            root, version = self._approved(c, plan.remediation_for_finding_id, "finding")
            original = self._row(c, t.engagements, root["engagement_id"])
            if (original["dataset_id"] != engagement["dataset_id"]
                    or engagement["period_start"] <= original["period_end"]
                    or plan.control_ids != [version["document"]["control_id"]]):
                raise AuditError("invalid_verification_scope")
        return plan.model_dump(mode="json")

    def _propose(self, c, engagement_id, kind, key, document, actor):
        """Create a proposal, or revise one only after an explicit request for changes."""
        existing = c.execute(sa.select(t.proposals).where(
            t.proposals.c.engagement_id == engagement_id, t.proposals.c.kind == kind,
            t.proposals.c.business_key == key)).mappings().first()
        version_number = 1
        if existing:
            root, latest, decision = self._latest(c, existing["id"])
            if latest["document"] == document:
                return self._proposal_output(c, root["id"])
            if not decision or decision["decision"] != "changes_requested":
                raise AuditError("proposal_exists_use_review")
            proposal_id = root["id"]
            version_number = latest["version"] + 1
        else:
            proposal_id = uid()
            c.execute(t.proposals.insert().values(id=proposal_id, engagement_id=engagement_id,
                                                  kind=kind, business_key=key))
        c.execute(t.proposal_versions.insert().values(
            id=uid(), proposal_id=proposal_id, version=version_number, document=document,
            created_by=actor.id, created_at=timestamp()))
        return self._proposal_output(c, proposal_id)

    def _verification_scope(self, c, engagement, plan, finding_id, control_id, start, end):
        """Keep autonomous retesting inside the explicit follow-up scope approved in the plan."""
        root, finding = self._approved(c, finding_id, "finding")
        document = plan["document"]
        if (not document.get("allow_followup_verification", False)
                or root["engagement_id"] != engagement["id"]
                or finding["document"]["control_id"] != control_id
                or not engagement["period_end"] < start <= end
                or end > engagement["period_end"] + timedelta(days=document["verification_window_days"])):
            raise AuditError("verification_outside_approved_scope", 403)
        return {**engagement, "period_start": start, "period_end": end}

    def _population(self, c, engagement, args):
        """Freeze all eligible members, policy and procedure under the current approved plan."""
        plan = self._plan(c, engagement["id"])
        if args.control_id not in plan["document"]["control_ids"]:
            raise AuditError("control_not_in_approved_plan", 403)
        control = self._row(c, t.controls, args.control_id)
        policy = self._row(c, t.policies, control["policy_id"])
        procedure = dict(c.execute(sa.select(t.procedures).where(
            t.procedures.c.control_id == args.control_id)).mappings().one())
        scope = engagement
        if args.verification_for_finding_id:
            scope = self._verification_scope(c, engagement, plan, args.verification_for_finding_id,
                args.control_id, args.verification_start, args.verification_end)
        members = [dict(row) for row in c.execute(sa.select(t.entities).where(
            t.entities.c.dataset_id == engagement["dataset_id"],
            t.entities.c.kind == control["entity_kind"],
            t.entities.c.active_from <= scope["period_end"],
            sa.or_(t.entities.c.active_to.is_(None),
                   t.entities.c.active_to >= scope["period_start"])).order_by(t.entities.c.id)).mappings()]
        payload = dict(plan_version_id=plan["id"], control=dict(control), policy=policy,
                       procedure=procedure, members=members,
                       verification_for_finding_id=args.verification_for_finding_id,
                       execution_scope={"period_start": scope["period_start"], "period_end": scope["period_end"]})
        id, _ = self._save_artifact(c, engagement["id"], "population", payload)
        return dict(population_snapshot_id=id, control_id=args.control_id,
                    plan_version_id=plan["id"], count=len(members), members=jsonable_encoder(members))

    def _current_population(self, c, engagement_id, id):
        """Block snapshots authorized by a superseded or unapproved plan version."""
        population = self._artifact(c, id, engagement_id, "population")
        if population["payload"]["plan_version_id"] != self._plan(c, engagement_id)["id"]:
            raise AuditError("stale_plan_snapshot")
        payload = population["payload"]
        if payload.get("verification_for_finding_id"):
            engagement = self._row(c, t.engagements, engagement_id)
            self._verification_scope(c, engagement, self._plan(c, engagement_id),
                payload["verification_for_finding_id"], payload["control"]["id"],
                date.fromisoformat(payload["execution_scope"]["period_start"]),
                date.fromisoformat(payload["execution_scope"]["period_end"]))
        return payload

    def _search(self, c, engagement, args):
        """Retrieve authorized candidates, preserving source facts and content-integrity checks."""
        population = self._current_population(c, engagement["id"], args.population_snapshot_id)
        sources = {r["id"]: dict(r) for r in c.execute(sa.select(t.sources)).mappings()}
        selected = set(args.source_ids) if args.source_ids is not None else set(sources)
        if not selected <= set(sources):
            raise AuditError("unknown_evidence_source")
        kinds = required_kinds(population["procedure"]["rule"])
        entity_ids = [e["id"] for e in population["members"]]
        records = []
        for row in c.execute(sa.select(t.evidence).where(
            t.evidence.c.dataset_id == engagement["dataset_id"],
            t.evidence.c.entity_id.in_(entity_ids), t.evidence.c.kind.in_(kinds),
            t.evidence.c.source_id.in_(selected)).order_by(t.evidence.c.id)).mappings():
            source = sources[row["source_id"]]
            if row["kind"] not in source["allowed_kinds"]:
                continue
            raw = dict(row)
            original = {key: value for key, value in raw.items() if key not in {"dataset_id", "fingerprint"}}
            records.append({**jsonable_encoder(raw), "authority": source["authority"],
                            "system": source["system"],
                            "integrity_valid": row["fingerprint"] == fingerprint(jsonable_encoder(original))})
        gaps = [dict(entity_id=id, evidence_kind=kind) for id in entity_ids for kind in kinds
                if not any(r["entity_id"] == id and r["kind"] == kind
                           and r["authority"] == ("secondary" if kind == "grc_approval" else "original")
                           for r in records)]
        payload = dict(population_snapshot_id=args.population_snapshot_id, records=records, gaps=gaps)
        id, _ = self._save_artifact(c, engagement["id"], "evidence", payload)
        return dict(evidence_snapshot_id=id, **payload)

    def _run_output(self, c, run_id):
        """Build counts exclusively from saved item-level calculated results."""
        run = self._row(c, t.artifacts, run_id)["payload"]
        results = [{k: row[k] for k in ("id", "entity_id", "outcome", "reason", "evidence_ids")}
                   for row in c.execute(sa.select(t.test_results).where(
                       t.test_results.c.run_id == run_id).order_by(t.test_results.c.entity_id)).mappings()]
        return dict(run_id=run_id, control_id=run["control_id"], purpose=run["purpose"],
                    results=results, counts={outcome: sum(r["outcome"] == outcome for r in results)
                                            for outcome in OUTCOMES})

    def _run(self, c, engagement, args):
        """Calculate and save full-population results; unchanged inputs reuse the same run."""
        population = self._current_population(c, engagement["id"], args.population_snapshot_id)
        evidence = self._artifact(c, args.evidence_snapshot_id, engagement["id"], "evidence")["payload"]
        if evidence["population_snapshot_id"] != args.population_snapshot_id:
            raise AuditError("evidence_population_mismatch")
        plan = self._plan(c, engagement["id"])
        finding_id = population.get("verification_for_finding_id") or plan["document"].get("remediation_for_finding_id")
        if finding_id:
            self._validate_plan(c, engagement, plan["document"])
        payload = dict(population_snapshot_id=args.population_snapshot_id,
                       evidence_snapshot_id=args.evidence_snapshot_id,
                       control_id=population["control"]["id"],
                       purpose="remediation" if finding_id else "audit", finding_id=finding_id)
        run_id, created = self._save_artifact(c, engagement["id"], "run", payload)
        if created:
            for entity in population["members"]:
                result = evaluate(population["procedure"]["rule"], entity, evidence["records"],
                                  {**engagement, **{key: date.fromisoformat(value) for key, value
                                      in population["execution_scope"].items()}}, population["policy"])
                c.execute(t.test_results.insert().values(
                    id=uid(), run_id=run_id, entity_id=entity["id"],
                    control_id=payload["control_id"], **result))
        return self._run_output(c, run_id)

    def _finding_document(self, c, engagement, result_ids, narrative):
        """Derive uneditable finding links only from failed results under the approved plan."""
        if len(set(result_ids)) != len(result_ids):
            raise AuditError("duplicate_result_reference")
        rows = [self._row(c, t.test_results, id) for id in result_ids]
        if any(row["outcome"] != "FAIL" for row in rows) or len({r["control_id"] for r in rows}) != 1:
            raise AuditError("finding_requires_failed_control_results")
        for row in rows:
            run = self._artifact(c, row["run_id"], engagement["id"], "run")["payload"]
            self._current_population(c, engagement["id"], run["population_snapshot_id"])
            if run["purpose"] != "audit":
                raise AuditError("finding_requires_audit_results")
        control = self._row(c, t.controls, rows[0]["control_id"])
        return {**FindingDocument.model_validate(narrative).model_dump(),
                "result_ids": sorted(result_ids), "control_id": control["id"], "policy_id": control["policy_id"],
                "evidence_ids": sorted({id for row in rows for id in row["evidence_ids"]})}

    def _request(self, c, engagement, args, actor):
        """Queue a scoped request; no external email is sent in this phase."""
        self._plan(c, engagement["id"])
        evidence = self._artifact(c, args.evidence_snapshot_id, engagement["id"], "evidence")["payload"]
        population = self._current_population(c, engagement["id"], evidence["population_snapshot_id"])
        if (args.recipient not in self.contacts.get(engagement["department"], [])
                or not set(args.entity_ids) <= {e["id"] for e in population["members"]}):
            raise AuditError("request_scope_or_recipient_not_permitted", 403)
        if args.purpose != "evidence":
            root, finding = self._approved(c, args.finding_id, "finding")
            if root["engagement_id"] != engagement["id"] or finding["document"]["control_id"] != population["control"]["id"]:
                raise AuditError("remediation_request_scope_mismatch", 403)
            if args.purpose == "implementation" and not self._action_plan(c, args.finding_id):
                raise AuditError("department_action_plan_required", 403)
        document = args.model_dump(mode="json", exclude={"operation_id"})
        document["entity_ids"] = sorted(set(document["entity_ids"]))
        # Several controls may depend on the same missing original record: one request covers them.
        gap_kinds = sorted({g["evidence_kind"] for g in evidence["gaps"]
            if g["entity_id"] in document["entity_ids"]})
        key = fingerprint(dict(engagement_id=engagement["id"],
            control_id=population["control"]["id"] if args.purpose != "evidence" or not gap_kinds else None,
            gap_kinds=gap_kinds, plan_version_id=population["plan_version_id"], entity_ids=document["entity_ids"],
            recipient=args.recipient, purpose=args.purpose, finding_id=args.finding_id, escalation=args.escalation))
        existing = c.execute(sa.select(t.evidence_requests).where(
            t.evidence_requests.c.business_key == key)).mappings().first()
        if existing:
            return dict(request_id=existing["id"], status=existing["status"],
                        review=self._proposal_output(c, existing["proposal_id"]) if existing["proposal_id"] else None)
        review = self._propose(c, engagement["id"], "escalation", key, document, actor) if args.escalation else None
        id = uid()
        status = "waiting_for_approval" if review else "queued"
        c.execute(t.evidence_requests.insert().values(
            id=id, engagement_id=engagement["id"], business_key=key, document=document,
            status=status, proposal_id=review["proposal_id"] if review else None, created_at=timestamp()))
        return dict(request_id=id, status=status, review=review)

    def _action_plan(self, c, finding_id):
        """Read the latest recorded department claim, not a verification outcome."""
        row = c.execute(sa.select(t.action_plans).where(t.action_plans.c.finding_id == finding_id)
                        .order_by(t.action_plans.c.created_at.desc(), t.action_plans.c.id.desc())).mappings().first()
        return dict(row) if row else None

    def _verify_closure(self, c, finding_id, run_id):
        """Require approved finding, department action and a later nonempty all-PASS retest."""
        finding, version = self._approved(c, finding_id, "finding")
        action_plan = self._action_plan(c, finding_id)
        if not action_plan or not run_id:
            raise AuditError("action_plan_and_verification_required", 403)
        run = self._row(c, t.artifacts, run_id)
        if run["kind"] != "run" or run["payload"].get("finding_id") != finding_id:
            raise AuditError("verification_finding_mismatch")
        engagement = self._row(c, t.engagements, run["engagement_id"])
        population = self._current_population(c, engagement["id"], run["payload"]["population_snapshot_id"])
        plan = self._plan(c, engagement["id"])
        self._validate_plan(c, engagement, plan["document"])
        results = self._run_output(c, run_id)
        if (results["purpose"] != "remediation" or not results["results"]
                or any(r["outcome"] != "PASS" for r in results["results"])
                or results["control_id"] != version["document"]["control_id"]):
            raise AuditError("independent_verification_not_passed", 403)
        return dict(finding_id=finding_id, finding_version_id=version["id"],
                    action_plan_id=action_plan["id"], verification_run_id=run_id)

    def invoke(self, name: str, raw: dict, actor: Principal) -> dict:
        """Validate one permitted tool call and atomically persist its actual result.

        BEGIN IMMEDIATE serializes local writers before checking receipts, so
        concurrent retries cannot both perform the same business action.
        """
        require_role(actor, "agent", "auditor")
        if name not in CONTRACTS:
            raise AuditError("unknown_tool", 404)
        inputs, outputs, _ = CONTRACTS[name]
        args = inputs.model_validate(raw)
        digest = fingerprint({"tool": name, "arguments": args.model_dump(mode="json")})
        with self.engine.begin() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            engagement = self._row(c, t.engagements, args.engagement_id)
            prior = c.execute(sa.select(t.action_receipts).where(
                t.action_receipts.c.actor_id == actor.id,
                t.action_receipts.c.operation_id == args.operation_id)).mappings().first()
            if prior:
                if prior["input_digest"] != digest:
                    raise AuditError("operation_id_reused_with_different_input")
                return prior["result"]
            if name == "get_audit_requirements":
                result = dict(engagement_id=engagement["id"], period_start=engagement["period_start"],
                    period_end=engagement["period_end"], controls=self._requirements(c, engagement),
                    sources=[dict(row) for row in c.execute(sa.select(t.sources)).mappings()])
            elif name == "draft_audit_plan":
                document = self._validate_plan(c, engagement, args.plan.model_dump(mode="json"))
                result = self._propose(c, engagement["id"], "plan", "work_program", document, actor)
            elif name == "get_test_population":
                result = self._population(c, engagement, args)
            elif name == "search_evidence":
                result = self._search(c, engagement, args)
            elif name == "run_control_test":
                result = self._run(c, engagement, args)
            elif name == "request_department_input":
                result = self._request(c, engagement, args, actor)
            elif name == "propose_finding":
                document = self._finding_document(c, engagement, args.result_ids, args.finding.model_dump())
                finding_key = None
                entities = {self._row(c, t.test_results, id)["entity_id"] for id in args.result_ids}
                for prior in c.execute(sa.select(t.proposals).where(
                        t.proposals.c.engagement_id == engagement["id"], t.proposals.c.kind == "finding")).mappings():
                    _, version, prior_decision = self._latest(c, prior["id"])
                    previous = version["document"]
                    if previous["control_id"] != document["control_id"]:
                        continue
                    previous_entities = {self._row(c, t.test_results, id)["entity_id"] for id in previous["result_ids"]}
                    if entities == previous_entities:
                        finding_key = prior["business_key"]
                    if entities & previous_entities and entities != previous_entities:
                        raise AuditError("finding_entities_already_covered")
                result = self._propose(c, engagement["id"], "finding",
                    finding_key or fingerprint([document["control_id"], sorted(entities)]), document, actor)
            else:
                root, _ = self._approved(c, args.finding_id, "finding")
                if root["engagement_id"] != engagement["id"]:
                    raise AuditError("finding_scope_mismatch", 403)
                action_plan = self._action_plan(c, args.finding_id)
                prior_closure = c.execute(sa.select(t.proposals).where(
                    t.proposals.c.kind == "closure", t.proposals.c.business_key == args.finding_id)).mappings().first()
                closure = self._proposal_output(c, prior_closure["id"]) if prior_closure else None
                if args.action == "propose_closure":
                    document = {**self._verify_closure(c, args.finding_id, args.verification_run_id),
                                "rationale": args.rationale}
                    closure = self._propose(c, engagement["id"], "closure", args.finding_id, document, actor)
                result = dict(finding_id=args.finding_id, action_plan=action_plan, closure=closure)
            result = outputs.model_validate(result).model_dump(mode="json")
            c.execute(t.action_receipts.insert().values(
                id=uid(), actor_id=actor.id, operation_id=args.operation_id,
                input_digest=digest, result=result))
            self._event(c, engagement["id"], actor, name, args.operation_id)
            return result

    def reviews(self, actor: Principal, proposal_id: str | None = None):
        """Return proposal histories to authenticated humans without editable evidence/results."""
        require_role(actor, "auditor", "reviewer")
        with self.engine.connect() as c:
            ids = [proposal_id] if proposal_id else list(c.execute(sa.select(t.proposals.c.id)).scalars())
            result = []
            for id in ids:
                root, _, _ = self._latest(c, id)
                versions = [dict(row) for row in c.execute(sa.select(t.proposal_versions).where(
                    t.proposal_versions.c.proposal_id == id).order_by(t.proposal_versions.c.version)).mappings()]
                decisions = [dict(row) for row in c.execute(sa.select(t.review_decisions).where(
                    t.review_decisions.c.version_id.in_([v["id"] for v in versions]))).mappings()]
                result.append({**root, **self._proposal_output(c, id), "versions": versions, "decisions": decisions})
            return result[0] if proposal_id else result

    def _is_closed(self, c, finding_id):
        """Check the saved closure decision before allowing changes to a closed finding."""
        row = c.execute(sa.select(t.proposals).where(
            t.proposals.c.kind == "closure", t.proposals.c.business_key == finding_id)).mappings().first()
        if row:
            return self._proposal_output(c, row["id"])["status"] == "approved"
        return False

    def save_draft(self, proposal_id: str, edit: DraftEdit, actor: Principal):
        """Save permitted human edits as a new pending version, retaining originals."""
        require_role(actor, "auditor", "reviewer")
        with self.engine.begin() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            root, latest, decision = self._latest(c, proposal_id)
            if latest["id"] != edit.expected_version_id:
                raise AuditError("stale_review_version")
            if root["kind"] == "closure" and decision and decision["decision"] == "approved":
                raise AuditError("closed_review_is_final")
            if root["kind"] == "finding" and self._is_closed(c, proposal_id):
                raise AuditError("closed_finding_is_final")
            allowed = {"plan": {"objective", "work_program", "control_ids", "allow_followup_verification", "verification_window_days"},
                       "finding": set(FindingDocument.model_fields), "escalation": {"subject", "message"},
                       "closure": {"rationale"}}[root["kind"]]
            if not set(edit.changes) <= allowed:
                raise AuditError("review_field_not_editable", 403)
            document = {**latest["document"], **edit.changes}
            engagement = self._row(c, t.engagements, root["engagement_id"])
            if root["kind"] == "plan":
                document = self._validate_plan(c, engagement, document)
            elif root["kind"] == "finding":
                narrative = {key: document[key] for key in FindingDocument.model_fields}
                document = self._finding_document(c, engagement, document["result_ids"], narrative)
            else:
                for key in allowed:
                    if not isinstance(document.get(key), str) or not 0 < len(document[key]) <= 2000:
                        raise AuditError("invalid_review_text")
            if document == latest["document"]:
                return self._proposal_output(c, proposal_id)
            c.execute(t.proposal_versions.insert().values(
                id=uid(), proposal_id=proposal_id, version=latest["version"] + 1,
                document=document, created_by=actor.id, created_at=timestamp()))
            if root["kind"] == "escalation":
                # Editing an approved message removes its release authorization immediately.
                c.execute(t.evidence_requests.update().where(
                    t.evidence_requests.c.proposal_id == proposal_id).values(
                    status="waiting_for_approval", document=document))
            self._event(c, root["engagement_id"], actor, "review_draft_saved", proposal_id)
            return self._proposal_output(c, proposal_id)

    def decide(self, proposal_id: str, decision: ReviewDecision, actor: Principal):
        """Only a human may approve/reject the exact current proposal version."""
        require_role(actor, "auditor", "reviewer")
        with self.engine.begin() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            root, version, prior = self._latest(c, proposal_id)
            if version["id"] != decision.expected_version_id:
                raise AuditError("stale_review_version")
            if version["created_by"] == actor.id and actor.role == "agent":
                raise AuditError("agent_cannot_approve", 403)
            if prior:
                if (prior["decision"], prior["reviewer_id"], prior["reason"]) == (
                        decision.decision, actor.id, decision.reason):
                    return self._proposal_output(c, proposal_id)
                raise AuditError("review_already_decided")
            engagement = self._row(c, t.engagements, root["engagement_id"])
            document = version["document"]
            if root["kind"] == "escalation" and document.get("overdue_request_id"):
                tracking = c.execute(sa.select(t.mail_followups).where(
                    t.mail_followups.c.request_id == document["overdue_request_id"])).mappings().first()
                if (not tracking or tracking["state"] != "waiting"
                        or tracking["escalation_proposal_id"] != proposal_id
                        or tracking["due_at"] != document.get("deadline_at")):
                    raise AuditError("obsolete_overdue_escalation")
            if decision.decision == "approved":
                if root["kind"] == "plan":
                    self._validate_plan(c, engagement, document)
                elif root["kind"] == "finding":
                    self._finding_document(c, engagement, document["result_ids"],
                        {key: document[key] for key in FindingDocument.model_fields})
                elif root["kind"] == "closure":
                    current = self._verify_closure(c, document["finding_id"], document["verification_run_id"])
                    if any(document[key] != value for key, value in current.items()):
                        raise AuditError("stale_closure_verification")
                else:
                    self._current_population(c, engagement["id"],
                        self._artifact(c, document["evidence_snapshot_id"], engagement["id"], "evidence")[
                            "payload"]["population_snapshot_id"])
            c.execute(t.review_decisions.insert().values(
                id=uid(), version_id=version["id"], decision=decision.decision,
                reviewer_id=actor.id, reviewer_role=actor.role, reason=decision.reason, created_at=timestamp()))
            if root["kind"] == "escalation" and decision.decision == "approved":
                # Approval releases the request to a future sender; it does not send it.
                c.execute(t.evidence_requests.update().where(
                    t.evidence_requests.c.proposal_id == proposal_id).values(status="queued", document=document))
            self._event(c, root["engagement_id"], actor, "review_" + decision.decision, proposal_id)
            return self._proposal_output(c, proposal_id)

    def record_action_plan(self, finding_id: str, document: ActionPlanInput, actor: Principal):
        """Record a human-entered department claim; independent verification is still mandatory."""
        require_role(actor, "auditor")
        with self.engine.begin() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            root, _ = self._approved(c, finding_id, "finding")
            if self._is_closed(c, finding_id):
                raise AuditError("closed_finding_is_final")
            payload = document.model_dump(mode="json")
            existing = self._action_plan(c, finding_id)
            if existing and existing["document"] == payload:
                return existing
            row = dict(id=uid(), finding_id=finding_id, document=payload,
                       recorded_by=actor.id, created_at=timestamp())
            c.execute(t.action_plans.insert().values(**row))
            self._event(c, root["engagement_id"], actor, "department_action_plan_recorded", row["id"])
            return row
