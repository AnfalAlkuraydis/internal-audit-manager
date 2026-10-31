"""Deadline-aware email queue, simulated dispatch and validated reply ingestion.

Clock injection makes multi-day behavior testable without sleeping. Delivery,
reply receipts and wake signals are durable; no model is used to invent facts.
"""
from datetime import datetime, timedelta, date
from uuid import uuid4
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from fastapi.encoders import jsonable_encoder
from backend.database import tables as t
from backend.database.repository import fingerprint, insert_unchanged
from backend.database.schemas import KIND_OWNER
from backend.agent.tools.contracts import SearchInput
from backend.auth import Principal
from backend.services.activity import utcnow, stamp, emit, wake
from backend.services.control_testing import evaluate
from backend.services.errors import AuditError
from backend.email.models import IncomingMail, FollowupEdit
from backend.email.simulated import SimulatedEmail

def next_reminder(now, due, interval_days):
    """Use the configured cadence, with a final pre-deadline reminder when useful.

    Missed intervals are not replayed as a burst. Once the pre-deadline point has
    passed, reminders return to the normal cadence while escalation awaits review.
    """
    normal = now + timedelta(days=interval_days)
    pre_deadline = due - timedelta(days=min(1, interval_days / 3))
    return min(normal, pre_deadline) if pre_deadline > now else normal

class MailService:
    """Operate the same normalized mail path for every audit; Phase 4 transport is simulated."""

    def __init__(self, audit, *, clock=utcnow, transport=None, default_deadline_days=7):
        """Inject time/transport for focused tests without changing business behavior."""
        self.audit = audit
        self.engine = audit.engine
        self.clock = clock
        self.transport = transport or SimulatedEmail()
        self.default_deadline_days = default_deadline_days

    def _tracking(self, c, request, now):
        """Create one durable schedule from request metadata, including older queued requests."""
        row = c.execute(sa.select(t.mail_followups).where(
            t.mail_followups.c.request_id == request["id"])).mappings().first()
        if row:
            return dict(row)
        document = request["document"]
        origin = min(datetime.fromisoformat(request["created_at"]), now)
        due = datetime.fromisoformat(document["due_at"]) if document.get("due_at") else (
            origin + timedelta(days=self.default_deadline_days))
        interval = document.get("reminder_interval_days", 3)
        values = dict(request_id=request["id"], due_at=stamp(due), interval_days=interval,
            next_reminder_at=stamp(next_reminder(now, due, interval)), reminder_count=0,
            state="waiting", escalation_proposal_id=None, updated_at=stamp(now))
        c.execute(t.mail_followups.insert().values(**values))
        return values

    def _queue(self, c, request, kind, ordinal, now, review=None):
        """Create a unique outgoing intent before delivery; retries reuse its message ID."""
        prior = c.execute(sa.select(t.mail_outbox).where(
            t.mail_outbox.c.request_id == request["id"], t.mail_outbox.c.kind == kind,
            t.mail_outbox.c.ordinal == ordinal)).mappings().first()
        if prior:
            return dict(prior)
        document = review["document"] if review else request["document"]
        id = str(uuid4())
        message_id = "<" + id + "@internal-audit.local>"
        envelope = dict(to=document["recipient"], subject=document["subject"],
            body=document["message"], request_id=request["id"], message_id=message_id,
            communication_kind=kind, transport="simulated")
        values = dict(id=id, request_id=request["id"], kind=kind, ordinal=ordinal,
            message_id=message_id, review_version_id=review["id"] if review else None,
            envelope=envelope, status="queued", attempts=0, error_code=None, created_at=stamp(now))
        c.execute(t.mail_outbox.insert().values(**values))
        return values

    def _authorize_send(self, c, request, outgoing):
        """Recheck scope and latest escalation version immediately before transport delivery."""
        if request["status"] in {"resolved", "cancelled"}:
            raise AuditError("request_no_longer_outstanding")
        evidence = self.audit._artifact(c, request["document"]["evidence_snapshot_id"],
                                       request["engagement_id"], "evidence")
        self.audit._current_population(c, request["engagement_id"],
                                       evidence["payload"]["population_snapshot_id"])
        if request["proposal_id"]:
            _, reviewed = self.audit._approved(c, request["proposal_id"], "escalation")
            if outgoing["review_version_id"] != reviewed["id"]:
                raise AuditError("stale_escalation_message")
        if outgoing["review_version_id"]:
            version = self.audit._row(c, t.proposal_versions, outgoing["review_version_id"])
            _, latest = self.audit._approved(c, version["proposal_id"], "escalation")
            if version["document"].get("overdue_request_id"):
                tracking = self._tracking(c, request, self.clock())
                if (tracking["escalation_proposal_id"] != version["proposal_id"]
                        or tracking["due_at"] != version["document"].get("deadline_at")
                        or self.clock() < datetime.fromisoformat(tracking["due_at"])):
                    raise AuditError("obsolete_overdue_escalation")
            if latest["id"] != version["id"]:
                raise AuditError("stale_escalation_message")
        if request["document"]["recipient"] not in self.audit.contacts.get(
                self.audit._row(c, t.engagements, request["engagement_id"])["department"], []):
            raise AuditError("recipient_no_longer_authorized", 403)

    def tick(self):
        """Discover requests, schedule due actions and deliver simulated mail once per intent."""
        now = self.clock()
        delivered = []
        with self.engine.begin() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            # Paused engagements retain requests but perform no simulated mail work.
            paused_engagements = sa.select(t.agent_sessions.c.engagement_id).where(
                t.agent_sessions.c.status == "paused",
                t.agent_sessions.c.engagement_id.is_not(None))
            requests = [dict(r) for r in c.execute(sa.select(t.evidence_requests).where(
                t.evidence_requests.c.engagement_id.not_in(paused_engagements))).mappings()]
            for request in requests:
                tracking = self._tracking(c, request, now)
                if tracking["state"] != "waiting" or request["status"] in {"resolved", "cancelled"}:
                    continue
                if request["status"] == "waiting_for_approval":
                    continue
                review = self.audit._latest(c, request["proposal_id"])[1] if request["proposal_id"] else None
                initial = self._queue(c, request, "initial", review["version"] if review else 0, now, review=review)
                if initial["status"] != "delivered":
                    continue
                due = datetime.fromisoformat(tracking["due_at"])
                if now >= datetime.fromisoformat(tracking["next_reminder_at"]):
                    number = tracking["reminder_count"] + 1
                    self._queue(c, request, "reminder", number, now, review=review)
                    c.execute(t.mail_followups.update().where(
                        t.mail_followups.c.request_id == request["id"]).values(
                        reminder_count=number, next_reminder_at=stamp(next_reminder(
                            now, due, tracking["interval_days"])), updated_at=stamp(now)))
                proposal_id = tracking["escalation_proposal_id"]
                if now >= due and not proposal_id:
                    document = {**request["document"], "overdue_request_id": request["id"], "deadline_at": tracking["due_at"],
                        "subject": ("Overdue: " + request["document"]["subject"])[:2000],
                        "message": ("The evidence deadline has passed. " + request["document"]["message"])[:2000]}
                    proposal = self.audit._propose(c, request["engagement_id"], "escalation",
                        "overdue:" + request["id"] + ":" + tracking["due_at"], document, Principal("followup-worker", "agent"))
                    proposal_id = proposal["proposal_id"]
                    c.execute(t.mail_followups.update().where(
                        t.mail_followups.c.request_id == request["id"]).values(escalation_proposal_id=proposal_id))
                    emit(c, "overdue:" + request["id"] + ":" + tracking["due_at"], "Overdue escalation ready for review",
                         "Waiting for Approval", engagement_id=request["engagement_id"],
                         record_type="review", record_id=proposal_id, now=now)
                    wake(c, request["engagement_id"], "Overdue escalation proposed", proposal_id, now=now)
                if proposal_id:
                    root, version, decision = self.audit._latest(c, proposal_id)
                    if decision and decision["decision"] == "approved":
                        self._queue(c, request, "overdue_escalation", int(fingerprint([version["id"]])[:12], 16), now, review=version)
            # Transport is a simulated ledger in this phase; delivery/status commit atomically.
            for outgoing in c.execute(sa.select(t.mail_outbox).where(
                    t.mail_outbox.c.status == "queued",
                    t.mail_outbox.c.request_id.in_([r["id"] for r in requests]))).mappings().all():
                outgoing = dict(outgoing)
                request = self.audit._row(c, t.evidence_requests, outgoing["request_id"])
                tracking = self._tracking(c, request, now)
                if tracking["state"] != "waiting":
                    c.execute(t.mail_outbox.update().where(t.mail_outbox.c.id == outgoing["id"]).values(status="cancelled"))
                    continue
                try:
                    self._authorize_send(c, request, outgoing)
                except AuditError as error:
                    # A pending review may later be approved; changed scope must not silently send.
                    if error.code.endswith("approval_required"):
                        continue
                    c.execute(t.mail_outbox.update().where(t.mail_outbox.c.id == outgoing["id"]).values(
                        status="cancelled", error_code=error.code))
                    if error.code == "stale_plan_snapshot":
                        c.execute(t.evidence_requests.update().where(
                            t.evidence_requests.c.id == request["id"]).values(status="cancelled"))
                        c.execute(t.mail_followups.update().where(
                            t.mail_followups.c.request_id == request["id"]).values(state="blocked_scope"))
                        wake(c, request["engagement_id"], "Outdated request cancelled after scope change", request["id"], now=now)
                    continue
                try:
                    with c.begin_nested():
                        self.transport.deliver(c, outgoing, now)
                except Exception:
                    c.execute(t.mail_outbox.update().where(t.mail_outbox.c.id == outgoing["id"]).values(
                        attempts=outgoing["attempts"] + 1, error_code="simulated_delivery_failed"))
                    emit(c, "delivery-failure:" + outgoing["id"] + ":" + str(outgoing["attempts"]),
                         "Simulated delivery failed; queued for retry", "Failed",
                         engagement_id=request["engagement_id"], record_type="request", record_id=request["id"], now=now)
                    continue
                if outgoing["kind"] == "initial":
                    c.execute(t.evidence_requests.update().where(
                        t.evidence_requests.c.id == request["id"]).values(status="sent"))
                delivered.append(outgoing["message_id"])
                emit(c, "delivered:" + outgoing["id"], "Simulated email delivered: " + outgoing["kind"],
                     engagement_id=request["engagement_id"], record_type="request", record_id=request["id"],
                     details={"message_id": outgoing["message_id"], "kind": outgoing["kind"]}, now=now)
        return delivered

    def update_schedule(self, request_id, value: FollowupEdit):
        """Persist a changed deadline/cadence; do not release pending escalation approval."""
        now = self.clock()
        with self.engine.begin() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            request = self.audit._row(c, t.evidence_requests, request_id)
            tracking = self._tracking(c, request, now)
            if tracking["state"] != "waiting":
                raise AuditError("request_already_resolved")
            c.execute(t.mail_followups.update().where(t.mail_followups.c.request_id == request_id).values(
                due_at=stamp(value.due_at), interval_days=value.reminder_interval_days,
                escalation_proposal_id=None,
                next_reminder_at=stamp(next_reminder(now, value.due_at, value.reminder_interval_days)),
                updated_at=stamp(now)))
            emit(c, str(uuid4()), "Evidence deadline updated", engagement_id=request["engagement_id"],
                 record_type="request", record_id=request_id, now=now)

    def _ingest(self, c, request, message, now):
        """Validate scope/provenance and append facts atomically, never rewriting evidence."""
        document = request["document"]
        engagement = self.audit._row(c, t.engagements, request["engagement_id"])
        evidence_snapshot = self.audit._artifact(c, document["evidence_snapshot_id"], engagement["id"], "evidence")
        population = self.audit._current_population(c, engagement["id"],
            evidence_snapshot["payload"]["population_snapshot_id"])
        purpose = document.get("purpose", "evidence")
        finding_id = document.get("finding_id")
        if purpose == "action_plan":
            root, _ = self.audit._approved(c, finding_id, "finding")
            if not message.action_plan or message.entities or message.evidence:
                raise AuditError("action_plan_reply_requires_department_plan")
            payload = message.action_plan.model_dump(mode="json")
            payload["source_reference"] = "email:" + message.message_id
            prior = self.audit._action_plan(c, finding_id)
            if not prior or prior["document"] != payload:
                c.execute(t.action_plans.insert().values(id=str(uuid4()), finding_id=finding_id,
                    document=payload, recorded_by="department:" + message.sender.casefold(), created_at=stamp(now)))
            return True, population["control"]["id"]
        if message.action_plan is not None:
            raise AuditError("action_plan_not_requested")
        allowed_ids = set(document["entity_ids"])
        if purpose == "implementation":
            if not message.verification_period:
                raise AuditError("verification_period_required")
            plan = self.audit._plan(c, engagement["id"])
            scope = self.audit._verification_scope(c, engagement, plan, finding_id,
                population["control"]["id"], message.verification_period.period_start,
                message.verification_period.period_end)
            kind = population["control"]["entity_kind"]
            for entity in message.entities:
                if entity.kind != kind or not (entity.active_from <= scope["period_end"]
                        and (entity.active_to is None or entity.active_to >= scope["period_start"])):
                    raise AuditError("implementation_entity_outside_scope")
                self.audit._row(c, t.sources, entity.source_id)
                insert_unchanged(c, t.entities, {**entity.model_dump(), "dataset_id": engagement["dataset_id"]})
                allowed_ids.add(entity.id)
        elif message.entities:
            raise AuditError("new_entities_not_authorized_for_request")
        for item in message.evidence:
            entity = self.audit._row(c, t.entities, item.entity_id)
            source = self.audit._row(c, t.sources, item.source_id)
            if (item.entity_id not in allowed_ids or entity["dataset_id"] != engagement["dataset_id"]
                    or KIND_OWNER[item.kind] != entity["kind"] or item.kind not in source["allowed_kinds"]):
                raise AuditError("reply_evidence_scope_mismatch")
            if item.supersedes_id:
                prior = self.audit._row(c, t.evidence, item.supersedes_id)
                if any(prior[key] != getattr(item, key) for key in (
                        "entity_id", "source_id", "source_record_id", "kind")) or prior["version"] >= item.version:
                    raise AuditError("invalid_evidence_replacement")
            insert_unchanged(c, t.evidence, {**item.model_dump(), "dataset_id": engagement["dataset_id"],
                "fingerprint": fingerprint(item.model_dump(mode="json"))})
        if not message.evidence:
            return False, population["control"]["id"]
        if purpose == "implementation":
            return True, population["control"]["id"]
        # Evidence may establish noncompliance: a late approval resolves the request, not the failure.
        fresh = self.audit._search(c, engagement, SearchInput(
            engagement_id=engagement["id"], operation_id=str(uuid4()),
            population_snapshot_id=evidence_snapshot["payload"]["population_snapshot_id"]))
        results = [evaluate(population["procedure"]["rule"], entity, fresh["records"],
                           engagement, population["policy"])
                   for entity in population["members"] if entity["id"] in allowed_ids]
        return bool(results) and all(r["outcome"] in {"PASS", "FAIL"} for r in results), population["control"]["id"]

    def receive(self, message: IncomingMail):
        """Match a delivered thread/sender, retain receipt history and wake only the matched audit."""
        now = self.clock()
        payload = message.model_dump(mode="json")
        digest = fingerprint(payload)
        with self.engine.begin() as c:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            prior = c.execute(sa.select(t.mail_inbox).where(t.mail_inbox.c.id == message.message_id)).mappings().first()
            if prior:
                if prior["digest"] != digest:
                    raise AuditError("incoming_message_id_conflict")
                return dict(prior)
            outgoing = c.execute(sa.select(t.mail_outbox).join(
                t.simulated_deliveries, t.simulated_deliveries.c.outbox_id == t.mail_outbox.c.id).where(
                t.mail_outbox.c.message_id == message.in_reply_to)).mappings().first()
            request = self.audit._row(c, t.evidence_requests, outgoing["request_id"]) if outgoing else None
            matched = request is not None and message.sender.strip().casefold() == request["document"]["recipient"].casefold()
            status, code = "unmatched", "thread_or_sender_not_matched"
            if matched and request["status"] in {"resolved", "cancelled"}:
                status, code = "ignored", "request_no_longer_outstanding"
            elif matched:
                self._tracking(c, request, now)
                try:
                    with c.begin_nested():
                        resolved, control_id = self._ingest(c, request, message, now)
                    status, code = ("resolved", "evidence_validated") if resolved else ("needs_clarification", "incomplete_reply")
                    c.execute(t.evidence_requests.update().where(
                        t.evidence_requests.c.id == request["id"]).values(status="resolved" if resolved else "received"))
                    c.execute(t.mail_followups.update().where(
                        t.mail_followups.c.request_id == request["id"]).values(
                        state="resolved" if resolved else "waiting",
                        next_reminder_at=stamp(next_reminder(now, datetime.fromisoformat(
                            self._tracking(c, request, now)["due_at"]),
                            self._tracking(c, request, now)["interval_days"])), updated_at=stamp(now)))
                    if request["document"].get("purpose", "evidence") == "evidence":
                        c.execute(t.work_items.update().where(t.work_items.c.engagement_id == request["engagement_id"],
                            t.work_items.c.state == "blocked", t.work_items.c.purpose == "audit").values(
                            state="ready", updated_at=stamp(now)))
                except (AuditError, ValueError, IntegrityError) as error:
                    status, code = "invalid", getattr(error, "code", "invalid_reply_evidence")
                emit(c, "incoming:" + message.message_id, "Department reply: " + status,
                     "Resumed" if status != "invalid" else "Failed", engagement_id=request["engagement_id"],
                     record_type="request", record_id=request["id"], details={"validation": code}, now=now)
                wake(c, request["engagement_id"], "Department reply available for agent reasoning",
                     request["id"], now=now)
            row = dict(id=message.message_id, request_id=request["id"] if matched else None, digest=digest,
                sender=message.sender, in_reply_to=message.in_reply_to, payload=payload,
                status=status, validation_code=code, received_at=stamp(now))
            c.execute(t.mail_inbox.insert().values(**row))
            return row
