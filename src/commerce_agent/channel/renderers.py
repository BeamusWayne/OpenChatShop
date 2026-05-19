"""Rich message renderers for CommerceAgent — contracts.md section 12.

Converts AgentMessage into validated, enriched structured output
for each of the 11 defined message types.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from commerce_agent.core.types import AgentMessage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_ORDER_STATUSES = frozenset({
    "pending", "paid", "processing", "shipped",
    "delivered", "cancelled", "refunded", "returning",
})

VALID_FIELD_TYPES = frozenset({
    "text", "number", "email", "phone", "select",
    "date", "textarea", "checkbox",
})

RENDERERS: dict[str, Any] = {}  # populated by @register


def register(name: str) -> Any:
    """Decorator that registers a render function by message type name."""
    def decorator(fn: Any) -> Any:
        RENDERERS[name] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def _require(payload: dict, key: str) -> Any:
    """Return *key* from *payload* or raise KeyError."""
    if key not in payload:
        raise KeyError(f"Missing required field: {key!r}")
    return payload[key]


# ---------------------------------------------------------------------------
# Per-type render functions
# ---------------------------------------------------------------------------


@register("text")
def _render_text(payload: dict) -> dict:
    content = _require(payload, "content")
    return {"content": content, "timestamp": datetime.now(timezone.utc).isoformat()}


@register("product_card")
def _render_product_card(payload: dict) -> dict:
    product_id = _require(payload, "product_id")
    name = _require(payload, "name")
    price = _require(payload, "price")
    if not isinstance(price, (int, float)) or price < 0:
        raise ValueError("price must be a number >= 0")
    result: dict[str, Any] = {
        "product_id": product_id, "name": name, "price": price,
    }
    for opt in ("image_url", "rating", "stock", "actions"):
        if opt in payload:
            result[opt] = payload[opt]
    return result


@register("product_list")
def _render_product_list(payload: dict) -> dict:
    products = _require(payload, "products")
    total = _require(payload, "total")
    if not isinstance(products, list):
        raise ValueError("products must be a list")
    if len(products) != total:
        raise ValueError(
            f"products length ({len(products)}) != total ({total})"
        )
    return {"products": products, "total": total}


@register("order_card")
def _render_order_card(payload: dict) -> dict:
    order_id = _require(payload, "order_id")
    status = _require(payload, "status")
    if status not in VALID_ORDER_STATUSES:
        raise ValueError(
            f"Invalid status {status!r}. Valid: {sorted(VALID_ORDER_STATUSES)}"
        )
    result: dict[str, Any] = {"order_id": order_id, "status": status}
    for opt in ("items", "total_amount", "created_at"):
        if opt in payload:
            result[opt] = payload[opt]
    return result


@register("logistics_timeline")
def _render_logistics_timeline(payload: dict) -> dict:
    order_id = _require(payload, "order_id")
    steps = _require(payload, "steps")
    if not isinstance(steps, list) or len(steps) == 0:
        raise ValueError("steps must be a non-empty list")
    for i, step in enumerate(steps):
        for field in ("status", "time", "location"):
            if field not in step:
                raise ValueError(
                    f"step[{i}] missing required field: {field!r}"
                )
    return {"order_id": order_id, "steps": steps}


@register("confirm")
def _render_confirm(payload: dict) -> dict:
    title = _require(payload, "title")
    description = _require(payload, "description")
    return {
        "title": title,
        "description": description,
        "confirm_label": payload.get("confirm_label", "确认"),
        "cancel_label": payload.get("cancel_label", "取消"),
    }


@register("form")
def _render_form(payload: dict) -> dict:
    fields = _require(payload, "fields")
    if not isinstance(fields, list):
        raise ValueError("fields must be a list")
    for i, f in enumerate(fields):
        for key in ("name", "type", "label", "required"):
            if key not in f:
                raise ValueError(f"fields[{i}] missing: {key!r}")
        if f["type"] not in VALID_FIELD_TYPES:
            raise ValueError(
                f"fields[{i}] invalid type {f['type']!r}"
            )
    result: dict[str, Any] = {"fields": fields}
    if "submit_label" in payload:
        result["submit_label"] = payload["submit_label"]
    return result


@register("rating")
def _render_rating(payload: dict) -> dict:
    prompt = _require(payload, "prompt")
    return {
        "prompt": prompt,
        "max_score": payload.get("max_score", 5),
        "min_score": payload.get("min_score", 1),
    }


@register("transfer")
def _render_transfer(payload: dict) -> dict:
    reason = _require(payload, "reason")
    result: dict[str, Any] = {"reason": reason}
    for opt in ("estimated_wait_seconds", "department"):
        if opt in payload:
            result[opt] = payload[opt]
    return result


@register("carousel")
def _render_carousel(payload: dict) -> dict:
    items = _require(payload, "items")
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    return {
        "items": items,
        "auto_play": payload.get("auto_play", False),
        "interval_ms": payload.get("interval_ms", 3000),
    }


@register("quick_replies")
def _render_quick_replies(payload: dict) -> dict:
    options = _require(payload, "options")
    if not isinstance(options, list) or len(options) == 0:
        raise ValueError("options must be a non-empty list")
    for i, opt in enumerate(options):
        for key in ("label", "value"):
            if key not in opt:
                raise ValueError(f"options[{i}] missing: {key!r}")
    return {"options": options}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class MessageRenderer:
    """Renders AgentMessage into validated, enriched structured output."""

    def render(self, message: AgentMessage) -> dict[str, Any]:
        """Dispatch by *message_type* and return a structured dict.

        Returns ``{type, payload, fallback_text}``.  On validation error the
        result is a text fallback containing the error description.
        """
        renderer = RENDERERS.get(message.message_type)
        if renderer is None:
            return self._text_fallback(message, "Unknown message type")

        try:
            enriched = renderer(message.payload)
        except (KeyError, ValueError) as exc:
            return self._text_fallback(message, str(exc))

        return {
            "type": message.message_type,
            "payload": enriched,
            "fallback_text": message.text_fallback,
        }

    @staticmethod
    def _text_fallback(message: AgentMessage, error: str) -> dict[str, Any]:
        return {
            "type": "text",
            "payload": {
                "content": message.text_fallback,
                "render_error": error,
            },
            "fallback_text": message.text_fallback,
        }
