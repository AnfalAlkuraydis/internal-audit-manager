"""Safe business errors shared by services and API responses."""
class AuditError(ValueError):
    """Expose a stable code and HTTP status, never credentials or database internals."""

    def __init__(self, code: str, status: int = 409):
        """Create an expected validation, permission, or workflow error."""
        self.code = code
        self.status = status
        super().__init__(code)
