"""Small local-demo bearer authentication; roles never come from request bodies."""
from dataclasses import dataclass, field
import hmac
import os
from typing import Literal
from backend.services.errors import AuditError

@dataclass(frozen=True)
class Principal:
    """Trusted identity created by authentication or an internal worker."""
    id: str
    role: Literal["auditor", "reviewer", "agent"]

@dataclass(frozen=True)
class AuthConfig:
    """Read local tokens without logging them; empty tokens grant no access."""
    auditor_token: str = field(default="", repr=False)
    reviewer_token: str = field(default="", repr=False)

    def __post_init__(self):
        """Reject ambiguous identities instead of choosing an arbitrary role."""
        if self.auditor_token and self.auditor_token == self.reviewer_token:
            raise AuditError("distinct_role_tokens_required", 503)

    @classmethod
    def from_env(cls):
        """Load the two optional demo credentials from environment variables."""
        return cls(os.getenv("AUDIT_AUDITOR_TOKEN", ""), os.getenv("AUDIT_REVIEWER_TOKEN", ""))

    def authenticate(self, token: str) -> Principal:
        """Map a valid token to a fixed human identity using constant-time comparison."""
        for expected, role in ((self.auditor_token, "auditor"), (self.reviewer_token, "reviewer")):
            if expected and hmac.compare_digest(token.encode(), expected.encode()):
                return Principal("demo-" + role, role)
        raise AuditError("authentication_required", 401)

def require_role(actor: Principal, *roles: str):
    """Enforce server-assigned roles for both direct service calls and API calls."""
    if actor.role not in roles:
        raise AuditError("role_not_permitted", 403)
