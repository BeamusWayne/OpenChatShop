"""Core data structures for OpenChatShop.

Defines all cross-module data types from the interface contracts:
  - Message types (Message, Attachment, UserMessage, AgentMessage)
  - Session and context types (SessionContext, TokenBudget)
  - Intent types (Intent, IntentInfo)
  - Tool types (ToolResult, ToolDefinition, ToolCall, ToolPermission,
               ValidationResult, CheckResult, RoutingRule)
  - LLM provider types (ProviderCapabilities, GenerateConfig,
                        LLMResponse, LLMChunk, TokenUsage)
  - Channel types (ChannelMessage, ChannelCapabilities)
  - FSM types (Transition)
  - Strategy types (Action)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal


class SessionMode(str, Enum):
    """Which entity is handling the session — bot or human."""
    AI_MODE = "ai_mode"
    TRANSFER_PENDING = "transfer_pending"
    HUMAN_MODE = "human_mode"

# ---------------------------------------------------------------------------
# §1 Core message types
# ---------------------------------------------------------------------------


@dataclass
class Message:
    """A single message within a conversation history."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Attachment:
    """A file/media attachment on a user message."""

    type: Literal["image", "file", "audio", "video"]
    url: str
    name: str | None = None
    size_bytes: int | None = None
    mime_type: str | None = None


@dataclass
class UserMessage:
    """Inbound message from the user, before any processing."""

    session_id: str
    content: str
    channel: str  # "web" | "wechat" | "miniprogram" | "app" | "api"
    user_id: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentMessage:
    """Outbound message from the agent, ready for channel adaptation."""

    message_type: str  # see contracts.md section 12
    payload: dict[str, Any]
    text_fallback: str
    suggestions: list[str] = field(default_factory=list)
    requires_confirmation: bool = False


@dataclass
class Intent:
    """Recognised user intent with confidence score."""

    name: str  # English snake_case identifier
    display_name: str  # Human-readable Chinese label
    confidence: float  # 0.0 - 1.0
    source: Literal["rule", "semantic", "llm"]
    entities: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# §3 LLM Provider types (also includes §4 ToolCall/TokenUsage)
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """A single tool invocation requested by the LLM."""

    tool_name: str
    params: dict[str, Any]
    call_id: str


@dataclass
class TokenUsage:
    """Token consumption for a single LLM call."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ToolDefinition:
    """Tool description visible to the LLM (separate from implementation)."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass
class ProviderCapabilities:
    """Declares what a given LLM provider supports."""

    tool_calling: bool
    streaming: bool
    vision: bool
    max_context_tokens: int
    supported_locales: list[str] = field(default_factory=list)


@dataclass
class GenerateConfig:
    """Configuration for a single LLM generation call."""

    temperature: float = 0.3
    max_tokens: int = 4096
    stop_sequences: list[str] = field(default_factory=list)
    timeout_seconds: int = 30
    retries: int = 2
    retry_delay_seconds: float = 1.0


@dataclass
class LLMResponse:
    """Complete response from a synchronous LLM call."""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None
    finish_reason: str = "stop"  # "stop" | "tool_calls" | "length" | "error"


@dataclass
class LLMChunk:
    """A single chunk from a streaming LLM response."""

    content_delta: str = ""
    tool_call_delta: ToolCall | None = None
    finish_reason: str | None = None


# ---------------------------------------------------------------------------
# §4-5 Tool types
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """Result returned by a tool execution."""

    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    sensitive_fields: list[str] = field(default_factory=list)
    latency_ms: int = 0


@dataclass
class ToolPermission:
    """Permission and safety metadata for a tool."""

    required_roles: list[str] = field(default_factory=list)
    sensitive_output: bool = False
    idempotent: bool = True
    requires_confirmation: bool = False
    confirmation_threshold: dict[str, Any] | None = None


@dataclass
class ValidationResult:
    """Result of JSON-Schema-based parameter validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    """Result of a business pre-check (inventory, permissions, etc.)."""

    passed: bool
    reason: str | None = None


@dataclass
class RoutingRule:
    """Maps intent patterns to tool sets for the ToolInjector."""

    intent_patterns: list[str] = field(default_factory=list)
    scenario: str | None = None
    tools: list[str] = field(default_factory=list)
    priority: int = 0


# ---------------------------------------------------------------------------
# §6 Channel types
# ---------------------------------------------------------------------------


@dataclass
class ChannelMessage:
    """A message after channel-specific adaptation."""

    channel: str
    content_type: str
    payload: dict[str, Any]
    was_downgraded: bool = False
    original_type: str | None = None


@dataclass
class ChannelCapabilities:
    """Declares what a given channel adapter supports."""

    supported_types: list[str] = field(default_factory=list)
    supports_rich_text: bool = False
    supports_images: bool = False
    supports_forms: bool = False
    max_message_length: int = 4096


# ---------------------------------------------------------------------------
# §7 Scenario FSM types
# ---------------------------------------------------------------------------


@dataclass
class Transition:
    """A single state transition in a ScenarioFSM."""

    from_state: str
    to_state: str
    trigger: str
    guard: Callable[[Any], bool] | None = None
    action: Callable[..., Awaitable[Any]] | None = None


# ---------------------------------------------------------------------------
# §8 Context Manager types
# ---------------------------------------------------------------------------


@dataclass
class SessionContext:
    """Full conversational context for an active session."""

    session_id: str
    user_id: str | None
    channel: str
    history: list[Message] = field(default_factory=list)
    summary: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    fsm_state: str = "idle"
    current_scenario: str | None = None
    token_usage: int = 0
    user_role: str = "customer"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    mode: SessionMode = SessionMode.AI_MODE
    human_agent_id: str | None = None


@dataclass
class TokenBudget:
    """Token budget allocation for a single LLM call."""

    total: int
    system_prompt: int
    history: int
    tool_results: int
    slot_entities: int
    history_used: int
    needs_compression: bool = False


# ---------------------------------------------------------------------------
# §9 Intent Engine types
# ---------------------------------------------------------------------------


@dataclass
class IntentInfo:
    """Metadata about a registered intent."""

    name: str
    display_name: str
    description: str
    sample_count: int
    typical_entities: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# §10 Strategy types
# ---------------------------------------------------------------------------


@dataclass
class Action:
    """Output of the strategy engine -- what to do next."""

    type: Literal[
        "reply",
        "tool_call",
        "confirm",
        "clarify",
        "transfer",
        "switch_scenario",
        "end",
    ]
    payload: dict[str, Any] = field(default_factory=dict)
