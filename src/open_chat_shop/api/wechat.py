"""WeChat Official Account webhook handlers."""
from __future__ import annotations

import hashlib
import logging
import os
import time
import xml.etree.ElementTree as ET

from fastapi import APIRouter, FastAPI, Query, Request, Response

from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.types import UserMessage

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
    fields = ("FromUserName", "ToUserName", "MsgType", "Content")
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

    if not content:
        content = ""

    user_msg = UserMessage(
        session_id=from_user,
        content=content,
        channel="wechat",
    )

    response = await _orchestrator.handle_message(user_msg)

    reply_xml = _build_reply_xml(
        to_user=from_user,
        from_user=to_user,
        content=response.text_fallback,
    )
    return Response(content=reply_xml, media_type="application/xml")


# ---------------------------------------------------------------------------
# Route registration helper
# ---------------------------------------------------------------------------


def setup_wechat_routes(app: FastAPI, orchestrator: DialogueOrchestrator) -> None:
    """Store the orchestrator reference and mount the WeChat router."""
    global _orchestrator
    _orchestrator = orchestrator
    app.include_router(wechat_router, prefix="/api/v1/wechat")
