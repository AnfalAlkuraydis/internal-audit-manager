"""Persist factual UI activity and wake signals; never fabricate completion states."""
from datetime import datetime, timezone
from uuid import uuid4
import sqlalchemy as sa
from backend.database import tables as t

def utcnow():
    """Return an aware UTC clock value, injectable elsewhere for scheduling tests."""
    return datetime.now(timezone.utc)

def stamp(value=None):
    """Normalize times to fixed-width UTC ISO strings for reliable SQLite comparisons."""
    return (value or utcnow()).astimezone(timezone.utc).isoformat(timespec="microseconds")

def emit(c, key, label, status="Completed", *, engagement_id=None, session_id=None,
         record_type=None, record_id=None, details=None, now=None):
    """Append one unique, committed-record-backed activity event."""
    if not c.execute(sa.select(t.activity.c.id).where(t.activity.c.event_key == key)).first():
        c.execute(t.activity.insert().values(event_key=key, session_id=session_id,
            engagement_id=engagement_id, status=status, label=label, record_type=record_type,
            record_id=record_id, details=details or {}, created_at=stamp(now)))

def wake(c, engagement_id, label, record_id, *, now=None):
    """Persist a wake counter so an arriving event survives worker restarts."""
    c.execute(t.agent_sessions.update().where(t.agent_sessions.c.engagement_id == engagement_id).values(
        wake_version=t.agent_sessions.c.wake_version + 1, updated_at=stamp(now)))
    emit(c, str(uuid4()), label, "Resumed", engagement_id=engagement_id,
         record_id=record_id, now=now)
