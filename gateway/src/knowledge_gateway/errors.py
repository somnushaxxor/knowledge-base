"""Domain errors returned by the gateway."""


class GatewayError(RuntimeError):
    """Base error safe to expose to an MCP caller."""


class ConfigurationError(GatewayError):
    """The gateway runtime configuration is invalid."""


class AuthorizationError(GatewayError):
    """The authenticated actor cannot perform the requested operation."""


class ValidationError(GatewayError):
    """An OKF document or bundle is invalid."""

    def __init__(self, message: str, issues: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.issues = issues or []


class NotFoundError(GatewayError):
    """The requested document does not exist."""


class ConflictError(GatewayError):
    """Optimistic concurrency or idempotency detected a conflict."""

