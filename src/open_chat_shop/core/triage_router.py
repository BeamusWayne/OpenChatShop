"""Triage routing gateway — the Multi-Agent front door (V2.0 module 1, feat-049).

The Triage gateway looks at a turn and decides one of three things:

* **handoff** — the message carries an extreme negative / escalation signal
  (complaint, legal threat, fraud accusation); a human should take over;
* **route** — hand the conversation to the domain specialist that owns the
  classified intent's tool (refund / sales / logistics …);
* **fallback** — no domain matched (greeting, thanks, unrecognised); the
  caller's general flow handles it.

It is a *pure decision* component: it reuses the existing rule-based intent
engine (it receives an already-classified ``Intent``) and adds escalation
detection + routing on top. It executes nothing and touches no existing flow —
turning a decision into an actual handoff / scoped execution is feat-051.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from open_chat_shop.core.domain_agent import AgentRegistry
from open_chat_shop.core.types import Intent

# Clear escalation / legal-threat / fraud signals. Deliberately narrow: mild
# dissatisfaction ("有点一般", "质量差") is NOT here, so a normal unhappy-but-
# routable customer is not force-handed to a human. Each phrase is unambiguous
# in user input (e.g. "工商局"/"市场监管" not bare "工商", which matches 工商银行).
_ESCALATION_SIGNALS: tuple[str, ...] = (
    "投诉",
    "起诉",
    "上诉",
    "维权",
    "消协",
    "消费者协会",
    "退一赔三",
    "骗子",
    "诈骗",
    "欺诈",
    "黑心",
    "曝光",
    "工商局",
    "市场监管",
)


def detect_escalation(text: str) -> bool:
    """Return True if *text* carries a clear escalation / negative signal."""
    return any(signal in text for signal in _ESCALATION_SIGNALS)


@dataclass(frozen=True)
class TriageDecision:
    """The outcome of triaging one turn (immutable)."""

    kind: Literal["handoff", "route", "fallback"]
    domain: str | None
    reason: str


class TriageRouter:
    """Decide handoff / route / fallback for a classified turn."""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def triage(self, text: str, intent: Intent) -> TriageDecision:
        """Return the routing decision for *text* with its classified *intent*.

        Escalation beats routing: an angry customer with an otherwise routable
        intent is still handed to a human.
        """
        if detect_escalation(text):
            return TriageDecision(kind="handoff", domain=None, reason="escalation")

        # intent.name is tool-name-aligned (configs/tool_routing.yaml), so the
        # registry resolves it to the domain that owns that tool.
        agent = self._registry.route_tool(intent.name)
        if agent is not None:
            return TriageDecision(kind="route", domain=agent.name, reason=f"intent:{intent.name}")

        return TriageDecision(kind="fallback", domain=None, reason="no_domain_match")
