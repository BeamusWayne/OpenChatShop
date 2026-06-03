"""Security layer for OpenChatShop.

Four-layer defense chain:
1. PromptInjectionDetector — rule-based injection detection
2. ContentSafetyFilter — PII masking + sensitive word filtering
3. PermissionChecker — RBAC tool access control
4. OutputSanitizer — output desensitization

Orchestrated by SecurityGuard.
See docs/design/contracts.md §11 and docs/design/security.md for details.
"""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import replace
from typing import Any, ClassVar

from open_chat_shop.core.exceptions import SecurityError
from open_chat_shop.core.types import UserMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Prompt Injection Detection
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    # Instruction override attempts (English)
    re.compile(r"ignore\s+(previous|prior|all|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(previous|prior|all|above|the)", re.IGNORECASE),
    re.compile(r"forget\s+(everything|all|previous|prior)", re.IGNORECASE),
    # Instruction override attempts (Chinese)
    re.compile(r"忽略.{0,4}(之前|上面|所有|全部).{0,4}(指令|规则|设定|约束)"),
    re.compile(r"忘记.{0,4}(之前|上面|所有|全部).{0,4}(指令|规则|设定)"),
    re.compile(r"不要(遵守|遵循|执行).{0,4}(之前|上面|任何|所有)"),
    re.compile(r"无视.{0,4}(之前|上面|所有).{0,4}(指令|规则|设定)"),
    # Role manipulation (English)
    re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"pretend\s+you\s+are\b", re.IGNORECASE),
    re.compile(r"act\s+as\s+(if\s+you\s+are|a|an)\b", re.IGNORECASE),
    # Role manipulation (Chinese)
    re.compile(r"你(现在|从现在起|以后).{0,4}(是|变成|成为)(一个|一名)?(管理员|超级用户|root|admin|系统)"),
    re.compile(r"假装(你是|你是一个|你是名)"),
    re.compile(r"扮演(一个|一名)?(管理员|系统|超级用户)"),
    # System prompt extraction
    re.compile(r"(告诉|说出|输出|显示|泄露)(我|一下)?(你的|系统)(提示|指令|prompt|系统提示)"),
    # System role injection
    re.compile(r"^\s*system\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*admin\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*root\s*:", re.IGNORECASE | re.MULTILINE),
    # SQL injection markers
    re.compile(r";\s*DROP\b", re.IGNORECASE),
    re.compile(r"UNION\s+SELECT\b", re.IGNORECASE),
    re.compile(r"--\s*$", re.MULTILINE),
]

# Heuristic thresholds
_MAX_INPUT_LENGTH = 2000
_MAX_SPECIAL_CHAR_RATIO = 0.4
_MIN_BASE64_LENGTH = 20


class PromptInjectionDetector:
    """Detects prompt injection attempts using rule-based patterns."""

    PATTERNS: list[re.Pattern[str]] = _INJECTION_PATTERNS

    def check(self, text: str) -> bool:
        """Return True if an injection attempt is detected."""
        if len(text) > _MAX_INPUT_LENGTH:
            logger.warning("Input exceeds max length: %d chars", len(text))
            return True

        if self._check_patterns(text):
            return True

        if self._check_base64(text):
            return True

        return bool(self._check_special_char_ratio(text))

    def _check_patterns(self, text: str) -> bool:
        """Match text against known injection patterns."""
        return any(pattern.search(text) for pattern in self.PATTERNS)

    def _check_base64(self, text: str) -> bool:
        """Heuristic: detect plausible base64-encoded command payloads."""
        b64_pattern = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
        for match in b64_pattern.finditer(text):
            candidate = match.group(0)
            if len(candidate) < _MIN_BASE64_LENGTH:
                continue
            try:
                decoded = base64.b64decode(candidate).decode("utf-8", errors="ignore")
                if any(p.search(decoded) for p in self.PATTERNS):
                    return True
            except Exception:
                pass
        return False

    def _check_special_char_ratio(self, text: str) -> bool:
        """Heuristic: excessive special characters may indicate obfuscation."""
        if not text:
            return False
        special_count = sum(1 for ch in text if not ch.isalnum() and not ch.isspace())
        ratio = special_count / len(text)
        return ratio > _MAX_SPECIAL_CHAR_RATIO


# ---------------------------------------------------------------------------
# 2. Content Safety Filter (PII masking)
# ---------------------------------------------------------------------------

_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Chinese ID cards (18 digits, last char may be X)
    # Must run BEFORE phone pattern to avoid partial match on ID digits
    (
        re.compile(
            r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])"
            r"(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"
        ),
        "[ID_CARD]",
    ),
    # Email addresses
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    # Chinese mobile phone numbers (11 digits starting with 1[3-9])
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[PHONE]"),
    # Credit card numbers (16 digits)
    (re.compile(r"(?<!\d)\d{16}(?!\d)"), "[CARD]"),
    # Bank card numbers (17-19 digits, avoids re-matching 16-digit cards)
    (re.compile(r"(?<!\d)\d{17,19}(?!\d)"), "[BANK_CARD]"),
]


class ContentSafetyFilter:
    """Filters content for PII and sensitive words."""

    PII_PATTERNS: ClassVar[list[re.Pattern[str]]] = [p for p, _ in _PII_PATTERNS]

    def check(self, text: str) -> tuple[bool, str]:
        """Return (is_safe, masked_text).

        is_safe is True if no PII was found (text is unchanged).
        masked_text has PII replaced with placeholder tokens.
        """
        masked = self.mask_pii(text)
        is_safe = masked == text
        if not is_safe:
            logger.info("PII detected and masked in input")
        return is_safe, masked

    def mask_pii(self, text: str) -> str:
        """Replace PII patterns in text with placeholder tokens."""
        result = text
        for pattern, replacement in _PII_PATTERNS:
            result = pattern.sub(replacement, result)
        return result


# ---------------------------------------------------------------------------
# 3. Permission Checker (RBAC)
# ---------------------------------------------------------------------------

_DEFAULT_RBAC: dict[str, Any] = {
    "roles": [
        {
            "name": "customer",
            "tools": [
                "query_order",
                "query_logistics",
                "search_product",
                "check_refund_eligibility",
                "create_refund",
                "cancel_order",
                "modify_address",
                "handoff_to_human",
            ],
        },
        {"name": "agent", "tools": ["*"]},
        {"name": "admin", "tools": ["*"]},
    ]
}


class PermissionChecker:
    """RBAC permission checker for tool access."""

    def __init__(self, config: dict | list) -> None:
        self._role_tools: dict[str, set[str]] = {}
        roles = config if isinstance(config, list) else config.get("roles", _DEFAULT_RBAC["roles"])
        for role_entry in roles:
            name = role_entry.get("name", "")
            tools = role_entry.get("tools", [])
            if "*" in tools:
                self._role_tools[name] = {"*"}
            else:
                self._role_tools[name] = set(tools)

    def has_permission(self, role: str, tool_name: str) -> bool:
        """Return True if the role is allowed to use the tool."""
        allowed = self._role_tools.get(role, set())
        if "*" in allowed:
            return True
        return tool_name in allowed

    def get_allowed_tools(self, role: str) -> list[str]:
        """Return sorted list of tools the role may access."""
        allowed = self._role_tools.get(role, set())
        if "*" in allowed:
            return ["*"]
        return sorted(allowed)


# ---------------------------------------------------------------------------
# 4. Output Sanitizer
# ---------------------------------------------------------------------------

_DEFAULT_SENSITIVE_FIELDS = frozenset({
    "password",
    "token",
    "secret",
    "api_key",
    "credit_card",
    "phone",
    "email",
    "id_card",
    "bank_card",
    "address",
})


class OutputSanitizer:
    """Sanitizes output to prevent data leakage."""

    def sanitize(
        self,
        data: dict,
        sensitive_fields: list[str] | None = None,
    ) -> dict:
        """Return a new dict with sensitive field values replaced by ***."""
        fields_to_mask = (
            frozenset(sensitive_fields)
            if sensitive_fields is not None
            else _DEFAULT_SENSITIVE_FIELDS
        )
        return self._sanitize_dict(data, fields_to_mask)

    def _sanitize_dict(self, data: dict, fields: frozenset[str]) -> dict:
        """Recursively sanitize a dict, returning a new dict."""
        sanitized: dict[str, Any] = {}
        for key, value in data.items():
            if key in fields:
                sanitized[key] = "***"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_dict(value, fields)
            elif isinstance(value, list):
                sanitized[key] = self._sanitize_list(value, fields)
            else:
                sanitized[key] = value
        return sanitized

    def _sanitize_list(self, items: list, fields: frozenset[str]) -> list:
        """Recursively sanitize list items."""
        result: list[Any] = []
        for item in items:
            if isinstance(item, dict):
                result.append(self._sanitize_dict(item, fields))
            elif isinstance(item, list):
                result.append(self._sanitize_list(item, fields))
            else:
                result.append(item)
        return result


# ---------------------------------------------------------------------------
# 5. Security Guard (orchestrator)
# ---------------------------------------------------------------------------

class SecurityGuard:
    """4-layer security chain: injection -> content -> permission -> output."""

    def __init__(self, config: dict) -> None:
        self.injection_detector = PromptInjectionDetector()
        self.content_filter = ContentSafetyFilter()
        self.permission_checker = PermissionChecker(config.get("rbac", {}))
        self.output_sanitizer = OutputSanitizer()

    def check_input(self, message: UserMessage) -> UserMessage:
        """Run injection + content checks on user input.

        Layer 1 (injection) raises SecurityError when an attack is detected.
        Layer 2 (PII) masks any detected PII and returns a *new* message
        carrying the masked content, so downstream modules (intent, LLM,
        history, tools) never see raw PII.  When no PII is present the
        original message is returned unchanged.
        """
        text = message.content

        # Layer 1: injection detection
        if self.injection_detector.check(text):
            logger.warning(
                "Prompt injection detected: session=%s user=%s",
                message.session_id,
                message.user_id,
            )
            raise SecurityError(
                "Input rejected: potential prompt injection detected",
                details={"session_id": message.session_id},
            )

        # Layer 2: content safety — mask PII and write it back into the message.
        is_safe, masked = self.content_filter.check(text)
        if is_safe:
            return message
        logger.info(
            "PII detected and masked in input (session=%s)",
            message.session_id,
        )
        return replace(message, content=masked)

    def check_permission(self, role: str, tool_name: str) -> None:
        """Raise SecurityError if the role cannot use the tool."""
        if not self.permission_checker.has_permission(role, tool_name):
            raise SecurityError(
                f"Role '{role}' is not permitted to use tool '{tool_name}'",
                details={"role": role, "tool_name": tool_name},
            )

    def sanitize_output(
        self,
        data: dict,
        sensitive_fields: list[str] | None = None,
    ) -> dict:
        """Sanitize output data, returning a new dict."""
        return self.output_sanitizer.sanitize(data, sensitive_fields)
