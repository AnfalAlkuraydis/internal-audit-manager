"""Exercise durable simulated-mail behavior using actual tools and a movable clock."""
import json
import unittest
from datetime import datetime, timedelta, timezone
import sqlalchemy as sa
from backend.database import tables as t
from backend.email.service import MailService, next_reminder
from backend.email.models import IncomingMail, FollowupEdit
from backend.services.errors import AuditError
from tests.audit_support import AuditFixture, ROOT

class FollowupTests(AuditFixture, unittest.TestCase):
    """No model calls: verify scheduler, sender validation, review gates and recovery."""
    def setUp(self):
        """Prepare a real missing-evidence request and deterministic time."""
        super().setUp()
        self.now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.plan(controls=["PR-02.v1"], allow_followup=True)
        population, evidence, run = self.execute_control("PR-02.v1")
        self.request = self.tool("request_department_input",
            evidence_snapshot_id=evidence["evidence_snapshot_id"], entity_ids=["PRJ-003"],
            recipient=self.service.contacts["Digital Risk"][0],
            subject="Original approval required", message="Supply original approval evidence.",
            due_at=(self.now + timedelta(days=7)).isoformat())
        self.mail = MailService(self.service, clock=lambda:self.now)
        self.mail.tick()
        with self.engine.connect() as c:
            self.outgoing = dict(c.execute(sa.select(t.mail_outbox)).mappings().one())

    def rows(self, table):
        """Read persisted records rather than infer delivery from a queued intent."""
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(sa.select(table)).mappings()]

    def reply(self, **changes):
        """Construct a normalized, correctly threaded department reply."""
        payload = dict(message_id="reply-1", in_reply_to=self.outgoing["message_id"],
            sender=self.service.contacts["Digital Risk"][0], body="Attached evidence")
        payload.update(changes)
        return IncomingMail.model_validate(payload)

    def test_cadence_deadline_and_restart_do_not_duplicate(self):
        """Three-day reminders survive a service restart and repeated scheduler ticks."""
        self.assertEqual(len(self.rows(t.simulated_deliveries)), 1)
        self.now += timedelta(days=3)
        self.mail = MailService(self.service, clock=lambda:self.now)
        self.mail.tick(); self.mail.tick()
        self.assertEqual(len(self.rows(t.simulated_deliveries)), 2)
        self.now += timedelta(days=3)
        self.mail.tick()
        self.assertEqual(len(self.rows(t.simulated_deliveries)), 3)
        self.assertEqual(next_reminder(self.now, self.now+timedelta(days=2), 3),
                         self.now+timedelta(days=1))

    def test_valid_reply_stops_reminders_and_duplicate_receipt_is_idempotent(self):
        """Late approval resolves the request while preserving a failing audit outcome."""
        evidence = json.loads((ROOT/"tests/fixtures/followup_messages.json").read_text())["messages"][0]["evidence"]
        message = self.reply(evidence=evidence)
        first = self.mail.receive(message)
        self.assertEqual(first["status"], "resolved")
        self.assertEqual(self.mail.receive(message), first)
        self.now += timedelta(days=10)
        self.mail.tick()
        self.assertEqual(len(self.rows(t.simulated_deliveries)), 1)
        self.assertEqual(len(self.rows(t.mail_inbox)), 1)
        _, _, run = self.execute_control("PR-02.v1")
        result = next(r for r in run["results"] if r["entity_id"]=="PRJ-003")
        self.assertEqual(result["outcome"], "FAIL")
        self.assertEqual(self.mail.receive(self.reply(message_id="reply-2"))["status"], "ignored")

    def test_invalid_partial_and_spoofed_reply_keep_request_open(self):
        """A body alone, unauthorized sender, or wrong evidence cannot satisfy a request."""
        self.assertEqual(self.mail.receive(self.reply(sender="intruder@example.test"))["status"],"unmatched")
        self.assertEqual(self.mail.receive(self.reply(message_id="partial"))["status"],"needs_clarification")
        self.now += timedelta(days=3)
        self.mail.tick()
        self.assertEqual(len(self.rows(t.simulated_deliveries)), 2)
        with self.assertRaises(AuditError):
            self.mail.receive(self.reply(message_id="partial", body="Altered same ID"))

    def test_overdue_escalation_requires_current_human_approval(self):
        """Deadline changes invalidate an old escalation and its approval cannot release mail."""
        self.now += timedelta(days=8)
        self.mail.tick()
        tracking = self.rows(t.mail_followups)[0]
        with self.engine.connect() as c:
            proposal = self.service._proposal_output(c, tracking["escalation_proposal_id"])
        self.assertFalse(any(r["kind"]=="overdue_escalation" for r in self.rows(t.mail_outbox)))
        self.mail.update_schedule(self.request["request_id"], FollowupEdit(
            due_at=self.now+timedelta(days=5), reminder_interval_days=2))
        with self.assertRaises(AuditError):
            self.decision(proposal)
        self.now += timedelta(days=6)
        self.mail.tick()
        with self.engine.connect() as c:
            proposal = self.service._proposal_output(c, self.rows(t.mail_followups)[0]["escalation_proposal_id"])
        self.decision(proposal)
        self.mail.tick(); self.mail.tick()
        self.assertEqual(sum(r["kind"]=="overdue_escalation" for r in self.rows(t.mail_outbox)),1)

    def test_delivery_failure_retries_same_intent_after_restart(self):
        """Failed simulated delivery cannot create a second outgoing message on restart."""
        class Broken:
            def deliver(self, c, outgoing, now):
                """Inject a transport fault before its transaction commits."""
                from backend.email.simulated import SimulatedEmail
                SimulatedEmail().deliver(c, outgoing, now)
                raise RuntimeError("test fault after ledger insert")
        self.now += timedelta(days=3)
        self.mail.transport=Broken()
        self.mail.tick()
        queue = [r for r in self.rows(t.mail_outbox) if r["status"]=="queued"]
        self.assertEqual(len(queue),1)
        self.mail=MailService(self.service,clock=lambda:self.now)
        self.mail.tick(); self.mail.tick()
        self.assertEqual(len(self.rows(t.mail_outbox)),2)
        self.assertEqual(len(self.rows(t.simulated_deliveries)),2)

    def test_resolved_request_invalidates_pending_overdue_review(self):
        """A late reply supersedes pending overdue escalation without blocking audit resumption."""
        self.now += timedelta(days=8)
        self.mail.tick()
        with self.engine.connect() as c:
            proposal = self.service._proposal_output(c, self.rows(t.mail_followups)[0]["escalation_proposal_id"])
        evidence = json.loads((ROOT/"tests/fixtures/followup_messages.json").read_text())["messages"][0]["evidence"]
        self.assertEqual(self.mail.receive(self.reply(evidence=evidence))["status"],"resolved")
        with self.assertRaises(AuditError):
            self.decision(proposal)
        from backend.agent.context import observe
        context=observe(self.service,self.engagement_id,self.now)
        self.assertFalse(any(p["proposal_id"]==proposal["proposal_id"] for p in context["proposals"]))

    def test_approved_escalation_edit_cannot_send_stale_wording(self):
        """Transport retry rechecks the exact approved version and cancels the older envelope."""
        self.now += timedelta(days=8)
        self.mail.tick()
        with self.engine.connect() as c:
            proposal=self.service._proposal_output(c,self.rows(t.mail_followups)[0]["escalation_proposal_id"])
        self.decision(proposal)
        class Broken:
            def deliver(self,c,outgoing,now):
                """Hold delivery while a human changes the proposed outgoing message."""
                raise RuntimeError("injected fault")
        self.mail.transport=Broken()
        self.mail.tick()
        from backend.agent.tools.contracts import DraftEdit
        edited=self.service.save_draft(proposal["proposal_id"],DraftEdit(
            expected_version_id=proposal["version_id"],changes={"message":"Human-reviewed replacement wording"}),self.reviewer)
        self.decision(edited)
        self.mail=MailService(self.service,clock=lambda:self.now)
        self.mail.tick()
        delivered=[r for r in self.rows(t.simulated_deliveries) if r["envelope"]["communication_kind"]=="overdue_escalation"]
        self.assertEqual(len(delivered),1)
        self.assertEqual(delivered[0]["envelope"]["body"],"Human-reviewed replacement wording")

    def test_shared_missing_record_resumes_both_dependent_controls(self):
        """Two controls missing the same approval share one request and both resume."""
        from backend.agent.tools.contracts import DraftEdit
        from backend.agent.context import observe, update_work
        with self.engine.connect() as c:
            root=c.execute(sa.select(t.proposals.c.id).where(t.proposals.c.kind=="plan")).scalar_one()
            plan=self.service._proposal_output(c,root)
        edited=self.service.save_draft(root,DraftEdit(expected_version_id=plan["version_id"],
            changes={"control_ids":["PR-02.v1","PR-03.v1"]}),self.reviewer)
        self.decision(edited)
        observe(self.service,self.engagement_id,self.now)
        requests=[]
        for control in ("PR-02.v1","PR-03.v1"):
            _,evidence,run=self.execute_control(control)
            update_work(self.service,self.engagement_id,run["run_id"],self.now)
            requests.append(self.tool("request_department_input",evidence_snapshot_id=evidence["evidence_snapshot_id"],
                entity_ids=["PRJ-003"],recipient=self.service.contacts["Digital Risk"][0],
                subject="Original approval",message="Supply the original approval record."))
        self.assertEqual(requests[0]["request_id"],requests[1]["request_id"])
        context=observe(self.service,self.engagement_id,self.now)
        self.assertFalse(any(n.startswith("unresolved_evidence_obligation") for n in context["needs"]))
        self.mail.tick()
        outgoing=next(r for r in self.rows(t.mail_outbox) if r["request_id"]==requests[0]["request_id"])
        evidence=json.loads((ROOT/"tests/fixtures/followup_messages.json").read_text())["messages"][0]["evidence"]
        receipt=self.mail.receive(self.reply(in_reply_to=outgoing["message_id"],evidence=evidence))
        self.assertEqual(receipt["status"],"resolved")
        self.assertEqual({r["state"] for r in self.rows(t.work_items) if r["plan_version_id"]==edited["version_id"]},{"ready"})

    def test_returned_finding_remains_actionable(self):
        """A request for changes is a revision obligation, not completion or approval."""
        from backend.agent.context import observe
        proposal=self.finding()
        self.decision(proposal,"changes_requested")
        context=observe(self.service,self.engagement_id,self.now)
        self.assertIn("revise_returned_proposal:finding:"+proposal["proposal_id"],context["needs"])
        self.assertTrue(context["waiting"])
