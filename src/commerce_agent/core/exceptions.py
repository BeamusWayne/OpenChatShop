"""Exception hierarchy for CommerceAgent.

All modules raise exceptions from this hierarchy so that the orchestrator
can handle them uniformly.  Each leaf exception carries a module-specific
error code prefix (SEC-, PROV-, CTX-, INTENT-, TOOL-, CHAN-).

See docs/design/contracts.md section 2 for the full specification.
"""

from __future__ import annotations


class CommerceAgentError(Exception):
    """Base exception for all CommerceAgent modules.

    Attributes:
        error_code: Module prefix + numeric code, e.g. "PROV-001".
        message: Human-readable error description.
        details: Arbitrary key-value pairs for debugging.
        recoverable: Whether the caller may retry or degrade gracefully.
    """

    def __init__(
        self,
        error_code: str,
        message: str,
        details: dict | None = None,
        recoverable: bool = True,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        self.recoverable = recoverable
        super().__init__(message)


class SecurityError(CommerceAgentError):
    """Security layer exception -- not recoverable by default."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(
            f"SEC-{abs(hash(message)) % 1000:03d}",
            message,
            details,
            recoverable=False,
        )


class ProviderError(CommerceAgentError):
    """LLM Provider exception."""

    def __init__(
        self, message: str, provider: str, details: dict | None = None
    ) -> None:
        super().__init__(
            f"PROV-{abs(hash(message)) % 1000:03d}",
            message,
            details,
        )
        self.provider = provider


class ContextError(CommerceAgentError):
    """Context management exception."""

    def __init__(
        self, message: str, session_id: str, details: dict | None = None
    ) -> None:
        super().__init__(
            f"CTX-{abs(hash(message)) % 1000:03d}",
            message,
            details,
        )
        self.session_id = session_id


class IntentError(CommerceAgentError):
    """Intent recognition exception."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(
            f"INTENT-{abs(hash(message)) % 1000:03d}",
            message,
            details,
        )


class ToolError(CommerceAgentError):
    """Tool execution exception."""

    def __init__(
        self, message: str, tool_name: str, details: dict | None = None
    ) -> None:
        super().__init__(
            f"TOOL-{abs(hash(message)) % 1000:03d}",
            message,
            details,
        )
        self.tool_name = tool_name


class ChannelError(CommerceAgentError):
    """Channel adapter exception."""

    def __init__(
        self, message: str, channel: str, details: dict | None = None
    ) -> None:
        super().__init__(
            f"CHAN-{abs(hash(message)) % 1000:03d}",
            message,
            details,
        )
        self.channel = channel
