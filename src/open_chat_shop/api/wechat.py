"""WeChat Official Account webhook handlers."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict

from fastapi import APIRouter, FastAPI, Query, Request, Response

from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.types import AgentMessage, UserMessage

try:
    from defusedxml.ElementTree import fromstring as _safe_fromstring
except ImportError:
    import xml.etree.ElementTree as _unsafe_et  # noqa: N813
    def _safe_fromstring(data: str | bytes) -> ET.Element:
        return _unsafe_et.fromstring(data)

logger = logging.getLogger(__name__)

wechat_router = APIRouter()

# Module-level orchestrator reference, set via setup_wechat_routes().
_orchestrator: DialogueOrchestrator | None = None

# WeChat Official Account requires the HTTP response within 5 seconds, else it
# shows the user a failure and retries the same MsgId (up to 3x). Cap the
# orchestrator turn just under that so we can always answer in time.
_WECHAT_DEADLINE_SECONDS = 4.5

# WeChat's documented "no reply, do not retry" acknowledgement is an empty body
# (the literal string "success" is also accepted). We return empty body on
# timeout so the platform stops retrying instead of re-delivering the message.
_WECHAT_EMPTY_ACK = ""

# Bounded LRU of recently-handled MsgIds, so WeChat retries of the *same*
# message are idempotent (return the cached reply / ack instead of re-running
# the orchestrator and double-spending the LLM). In-process only: matches the
# single-worker default (see docs/production-hardening-audit.md); multi-worker
# would need shared (Redis) dedup.
_MSGID_CACHE_MAX = 1024
_seen_msgids: OrderedDict[str, str] = OrderedDict()


def _remember_msgid(msg_id: str, reply: str) -> None:
    """Record the reply produced for *msg_id*, evicting oldest beyond the cap."""
    if not msg_id:
        return
    _seen_msgids[msg_id] = reply
    _seen_msgids.move_to_end(msg_id)
    while len(_seen_msgids) > _MSGID_CACHE_MAX:
        _seen_msgids.popitem(last=False)


# ---------------------------------------------------------------------------
# WeChat signature verification
# ---------------------------------------------------------------------------


def _verify_signature(token: str, timestamp: str, nonce: str, signature: str) -> bool:
    """Return True if the SHA1 signature matches WeChat's algorithm."""
    parts = sorted([token, timestamp, nonce])
    joined = "".join(parts)
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()
    return digest == signature


def _get_token() -> str | None:
    """Return the configured WeChat token, or None if not set."""
    token = os.environ.get("WECHAT_TOKEN", "")
    return token if token else None


# ---------------------------------------------------------------------------
# GET /callback — server verification
# ---------------------------------------------------------------------------


@wechat_router.get("/callback")
async def verify(
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
) -> Response:
    token = _get_token()
    if token is None:
        return Response(
            content="WeChat channel not configured",
            status_code=503,
        )

    if not _verify_signature(token, timestamp, nonce, signature):
        return Response(content="Forbidden", status_code=403)

    return Response(content=echostr, media_type="text/plain")


# ---------------------------------------------------------------------------
# POST /callback — incoming message
# ---------------------------------------------------------------------------


def _parse_xml_body(body: bytes) -> dict[str, str]:
    """Extract key fields from a WeChat XML message payload."""
    root = _safe_fromstring(body)
    fields = ("FromUserName", "ToUserName", "MsgType", "Content", "MsgId")
    result: dict[str, str] = {}
    for field in fields:
        el = root.find(field)
        result[field] = el.text if el is not None and el.text else ""
    return result


def _build_reply_xml(to_user: str, from_user: str, content: str) -> str:
    """Format a text reply in WeChat XML envelope.

    Built with ElementTree so that all text (the routing fields and the
    user/business-supplied ``content``) is XML-escaped automatically. This
    prevents a stray ``]]>`` terminator or raw ``<``/``&`` in the content from
    breaking the envelope or injecting markup, which naive CDATA string
    concatenation allowed.
    """
    root = ET.Element("xml")
    ET.SubElement(root, "ToUserName").text = to_user
    ET.SubElement(root, "FromUserName").text = from_user
    ET.SubElement(root, "CreateTime").text = str(int(time.time()))
    ET.SubElement(root, "MsgType").text = "text"
    ET.SubElement(root, "Content").text = content
    return ET.tostring(root, encoding="unicode")


@wechat_router.post("/callback")
async def receive_message(request: Request) -> Response:
    if _orchestrator is None:
        return Response(content="Service not configured", status_code=503)

    token = _get_token()
    if token is None:
        return Response(
            content="WeChat channel not configured",
            status_code=503,
        )

    # Verify signature from query params
    signature = request.query_params.get("signature", "")
    timestamp = request.query_params.get("timestamp", "")
    nonce = request.query_params.get("nonce", "")

    if not _verify_signature(token, timestamp, nonce, signature):
        return Response(content="Forbidden", status_code=403)

    # Parse XML body
    body = await request.body()
    try:
        msg_data = _parse_xml_body(body)
    except ET.ParseError:
        logger.warning("Failed to parse WeChat XML body")
        return Response(content="Bad request", status_code=400)

    from_user = msg_data["FromUserName"]
    to_user = msg_data["ToUserName"]
    content = msg_data["Content"]
    msg_id = msg_data["MsgId"]

    if not content:
        content = ""

    # Idempotency: WeChat re-delivers the same MsgId on any perceived failure.
    # If we have already produced a reply for this MsgId, return it verbatim
    # instead of re-running the orchestrator (avoids duplicate side effects and
    # double LLM spend).
    if msg_id and msg_id in _seen_msgids:
        cached = _seen_msgids[msg_id]
        _seen_msgids.move_to_end(msg_id)
        if not cached:
            return Response(content=_WECHAT_EMPTY_ACK, media_type="text/plain")
        return Response(content=cached, media_type="application/xml")

    user_msg = UserMessage(
        session_id=from_user,
        content=content,
        channel="wechat",
        # FromUserName is the WeChat OpenID — a signature-verified, per-user
        # identity. Bind it as user_id so order tools enforce ownership
        # (get_for_user) instead of running unauthenticated (audit IDOR/BOLA).
        user_id=from_user,
    )

    # Hard 5s SLA: cap the turn at _WECHAT_DEADLINE_SECONDS. On timeout, ack with
    # an empty body so WeChat stops retrying; the slow turn is abandoned rather
    # than left to blow the deadline and trigger duplicate re-delivery.
    try:
        response: AgentMessage = await asyncio.wait_for(
            _orchestrator.handle_message(user_msg),
            timeout=_WECHAT_DEADLINE_SECONDS,
        )
    except TimeoutError:
        logger.warning(
            "WeChat turn exceeded %.1fs deadline; acking empty (session=%s msg_id=%s)",
            _WECHAT_DEADLINE_SECONDS,
            from_user,
            msg_id,
        )
        _remember_msgid(msg_id, _WECHAT_EMPTY_ACK)
        return Response(content=_WECHAT_EMPTY_ACK, media_type="text/plain")

    reply_xml = _build_reply_xml(
        to_user=from_user,
        from_user=to_user,
        content=response.text_fallback,
    )
    _remember_msgid(msg_id, reply_xml)
    return Response(content=reply_xml, media_type="application/xml")


# ---------------------------------------------------------------------------
# Route registration helper
# ---------------------------------------------------------------------------


def setup_wechat_routes(app: FastAPI, orchestrator: DialogueOrchestrator) -> None:
    """Store the orchestrator reference and mount the WeChat router."""
    global _orchestrator
    _orchestrator = orchestrator
    app.include_router(wechat_router, prefix="/api/v1/wechat")
