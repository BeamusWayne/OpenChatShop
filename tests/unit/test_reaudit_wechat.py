"""Re-audit regression tests for the WeChat 5s-SLA deadline (cluster: wechat).

Verified finding: the webhook capped the orchestrator turn with
``asyncio.wait_for`` and, on timeout, acked WeChat with an empty body. But
``wait_for`` *cancels* the in-flight coroutine, so a tool write that had
already committed (e.g. ``create_refund``) was torn down mid-turn and then
hidden behind the empty ack — a silent partial failure. Worse, WeChat then
re-delivers the same MsgId and, with the turn destroyed, the side effect could
be re-executed (double refund / double LLM spend).

The fix makes the deadline NON-DESTRUCTIVE: the turn runs as a background task
that is *not* cancelled when the HTTP deadline fires. We ack empty only for the
response; the turn finishes its committed write and backfills the MsgId cache
with its real reply, so a re-delivery returns that reply and never re-runs the
orchestrator.

Each test below FAILS against the pre-fix ``wait_for`` implementation and
PASSES after the fix. Comments pin the *intent* (why the behaviour matters),
per repo Rule 9.
"""
from __future__ import annotations

import asyncio
import hashlib

import pytest

from open_chat_shop.api import wechat
from open_chat_shop.core.types import AgentMessage, UserMessage

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeRequest:
    """Minimal starlette.Request stand-in: only .query_params.get and .body()."""

    def __init__(self, query: dict[str, str], body: bytes) -> None:
        self.query_params = query
        self._body = body

    async def body(self) -> bytes:
        return self._body


def _valid_query() -> dict[str, str]:
    """Signature params that pass _verify_signature for token 'test-token'."""
    token, timestamp, nonce = "test-token", "1700000000", "abc"
    # SHA1 here matches WeChat's documented signature scheme (not security).
    sig = hashlib.sha1("".join(sorted([token, timestamp, nonce])).encode()).hexdigest()
    return {"signature": sig, "timestamp": timestamp, "nonce": nonce}


def _wechat_xml(content: str, *, from_user: str = "openid-1", msg_id: str = "m1") -> bytes:
    return (
        "<xml>"
        "<ToUserName><![CDATA[gh_app]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        f"<MsgId>{msg_id}</MsgId>"
        "</xml>"
    ).encode()


class _CommittingOrchestrator:
    """Simulates a turn that COMMITS a side effect (a refund) and only then
    returns its reply.

    The side effect fires after the response deadline (gated by ``release`` so
    the test controls timing deterministically). The pre-fix ``wait_for`` would
    cancel this coroutine at the deadline, so ``committed`` would never flip and
    ``calls`` of the side effect would be lost; the fix lets it run to the end.
    """

    def __init__(self, release: asyncio.Event, reply: str = "退款已提交") -> None:
        self.calls = 0
        self.committed = False
        self.completed = asyncio.Event()
        self._release = release
        self._reply = reply

    async def handle_message(self, message: UserMessage) -> AgentMessage:
        self.calls += 1
        # Block until the test has already observed the empty ack, proving the
        # turn outlives the HTTP response rather than racing it.
        await self._release.wait()
        # The committed write — must NOT be skipped by deadline cancellation.
        self.committed = True
        result = AgentMessage(
            message_type="text",
            payload={"content": self._reply},
            text_fallback=self._reply,
        )
        self.completed.set()
        return result


def _inflight() -> set[asyncio.Task[AgentMessage]]:
    """In-flight background turns, tolerant of pre-fix builds without the set.

    Using getattr (rather than a hard attribute reference) keeps these tests as
    a *behavioural* RED against the old wait_for implementation: they reach and
    fail the real assertions (committed write survives, retry returns the real
    reply) instead of erroring out on a missing symbol.
    """
    tasks: set[asyncio.Task[AgentMessage]] = getattr(wechat, "_inflight_tasks", set())
    return tasks


@pytest.fixture(autouse=True)
def _isolate_wechat(monkeypatch: pytest.MonkeyPatch):
    """Reset module-level orchestrator, dedup cache, and in-flight task set."""
    monkeypatch.setenv("WECHAT_TOKEN", "test-token")
    wechat._seen_msgids.clear()
    _inflight().clear()
    yield
    # Drain any background turn this test spawned so it does not leak into the
    # next test's event loop.
    for task in list(_inflight()):
        task.cancel()
    wechat._seen_msgids.clear()
    _inflight().clear()
    wechat._orchestrator = None


# ---------------------------------------------------------------------------
# Non-destructive deadline
# ---------------------------------------------------------------------------


class TestDeadlineIsNonDestructive:
    """The HTTP deadline must not cancel a turn whose write already committed."""

    async def test_committed_write_survives_the_deadline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        release = asyncio.Event()
        orch = _CommittingOrchestrator(release)
        wechat._orchestrator = orch
        monkeypatch.setattr(wechat, "_WECHAT_DEADLINE_SECONDS", 0.02)

        resp = await wechat.receive_message(
            _FakeRequest(_valid_query(), _wechat_xml("退款", msg_id="rf-1"))
        )

        # Deadline fired first: WeChat is acked empty (so it stops retrying).
        assert resp.status_code == 200
        assert resp.body == b""
        # The turn is still alive in the background — NOT cancelled.
        assert orch.committed is False  # gated on release, not yet fired
        assert len(_inflight()) == 1  # pre-fix: 0 (turn was cancelled)

        # Now let the turn finish its committed write.
        release.set()
        await asyncio.wait_for(orch.completed.wait(), timeout=1.0)

        # Pre-fix: wait_for cancelled the coroutine at 0.02s, so this commit was
        # silently dropped (committed stays False). It must complete.
        assert orch.committed is True
        assert orch.calls == 1

    async def test_turn_is_not_cancelled_at_deadline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        release = asyncio.Event()
        orch = _CommittingOrchestrator(release)
        wechat._orchestrator = orch
        monkeypatch.setattr(wechat, "_WECHAT_DEADLINE_SECONDS", 0.02)

        await wechat.receive_message(
            _FakeRequest(_valid_query(), _wechat_xml("退款", msg_id="rf-2"))
        )

        # The defining symptom of the bug: wait_for would have left ZERO live
        # tasks (the turn was cancelled). The fix keeps exactly one running.
        tasks = tuple(_inflight())
        assert len(tasks) == 1
        task = tasks[0]
        assert not task.cancelled()
        assert not task.done()
        release.set()
        await asyncio.wait_for(task, timeout=1.0)
        assert not task.cancelled()


# ---------------------------------------------------------------------------
# Re-delivery after a deadline returns the REAL reply (and runs once)
# ---------------------------------------------------------------------------


class TestRedeliveryAfterDeadline:
    """Once the background turn finishes, a WeChat re-delivery of the same MsgId
    must return the turn's real reply — not the placeholder empty ack — and must
    not re-run the orchestrator (no double execution of the committed write)."""

    async def test_redelivery_returns_backfilled_reply_without_rerun(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        release = asyncio.Event()
        orch = _CommittingOrchestrator(release, reply="退款已提交")
        wechat._orchestrator = orch
        monkeypatch.setattr(wechat, "_WECHAT_DEADLINE_SECONDS", 0.02)
        body = _wechat_xml("退款", msg_id="rf-3")

        # First delivery times out -> empty ack, turn keeps running.
        first = await wechat.receive_message(_FakeRequest(_valid_query(), body))
        assert first.body == b""

        # Let the background turn finish and run its done-callback (which
        # backfills the cache). add_done_callback is scheduled on the loop, so
        # yield once after completion to let it execute.
        release.set()
        for task in tuple(_inflight()):
            await asyncio.wait_for(task, timeout=1.0)
        await asyncio.sleep(0)  # let the done-callback run

        # WeChat re-delivers the SAME MsgId.
        second = await wechat.receive_message(_FakeRequest(_valid_query(), body))

        # The orchestrator ran exactly once across timeout + retry.
        assert orch.calls == 1
        # The retry now carries the real reply, not the empty ack.
        assert second.status_code == 200
        assert second.body != b""
        assert "退款已提交" in second.body.decode("utf-8")
        assert second.media_type == "application/xml"

    async def test_redelivery_during_inflight_turn_does_not_rerun(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A retry that arrives WHILE the first turn is still in flight (before it
        # commits) must also not start a second turn — the empty-ack cache entry
        # short-circuits it. This is the double-execution guard.
        release = asyncio.Event()
        orch = _CommittingOrchestrator(release)
        wechat._orchestrator = orch
        monkeypatch.setattr(wechat, "_WECHAT_DEADLINE_SECONDS", 0.02)
        body = _wechat_xml("退款", msg_id="rf-4")

        first = await wechat.receive_message(_FakeRequest(_valid_query(), body))
        assert first.body == b""
        # Retry arrives before release -> turn still in flight.
        second = await wechat.receive_message(_FakeRequest(_valid_query(), body))

        assert orch.calls == 1  # NOT re-run
        assert second.body == b""  # still the cached empty ack

        release.set()
        for task in tuple(_inflight()):
            await asyncio.wait_for(task, timeout=1.0)
        assert orch.calls == 1  # still exactly one execution


# ---------------------------------------------------------------------------
# Fast path is unchanged
# ---------------------------------------------------------------------------


class TestFastPathUnchanged:
    """A turn that finishes within the deadline returns its reply synchronously
    and leaves no background task behind (the common case)."""

    async def test_fast_turn_returns_reply_and_leaves_no_task(self) -> None:
        release = asyncio.Event()
        release.set()  # unblock immediately -> finishes within the deadline
        orch = _CommittingOrchestrator(release, reply="您好")
        wechat._orchestrator = orch

        resp = await wechat.receive_message(
            _FakeRequest(_valid_query(), _wechat_xml("在吗", msg_id="ok-1"))
        )

        assert resp.status_code == 200
        assert "您好" in resp.body.decode("utf-8")
        assert resp.media_type == "application/xml"
        assert orch.calls == 1
        # The done-callback removes the finished task; let it run, then assert.
        await asyncio.sleep(0)
        assert len(_inflight()) == 0
