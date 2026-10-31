"""Exactly-once simulated delivery ledger, committed with its outbox status."""
from uuid import uuid4
import sqlalchemy as sa
from backend.database import tables as t
from backend.services.activity import stamp

class SimulatedEmail:
    """Replace transport only; all requests, evidence and agent work remain actual records."""

    def deliver(self, c, outgoing, now):
        """Record one delivery per outbox action inside the caller's database transaction."""
        existing = c.execute(sa.select(t.simulated_deliveries).where(
            t.simulated_deliveries.c.outbox_id == outgoing["id"])).mappings().first()
        if not existing:
            c.execute(t.simulated_deliveries.insert().values(id=str(uuid4()),
                outbox_id=outgoing["id"], message_id=outgoing["message_id"],
                envelope=outgoing["envelope"], delivered_at=stamp(now)))
        c.execute(t.mail_outbox.update().where(t.mail_outbox.c.id == outgoing["id"]).values(
            status="delivered", attempts=outgoing["attempts"] + 1, error_code=None))
