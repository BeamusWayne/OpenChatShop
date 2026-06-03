"""Integration tests for channel registry, channel config, and WeChat webhook."""
from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_chat_shop.api.wechat import setup_wechat_routes
from open_chat_shop.channel.miniprogram import MiniProgramAdapter
from open_chat_shop.channel.registry import ChannelRegistry, default_registry
from open_chat_shop.channel.web import WebAdapter, WechatAdapter
from open_chat_shop.core.config import ChannelsFileModel, ConfigLoader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signature(token: str, timestamp: str, nonce: str) -> str:
    """Compute the WeChat SHA1 signature."""
    parts = sorted([token, timestamp, nonce])
    joined = "".join(parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def _wechat_xml(from_user: str, to_user: str, content: str) -> str:
    """Build a minimal WeChat text-message XML body."""
    return (
        "<xml>"
        f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        f"<CreateTime>1234567890</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        "</xml>"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wechat_token(monkeypatch):
    """Set WECHAT_TOKEN for the duration of a test, then remove it."""
    monkeypatch.setenv("WECHAT_TOKEN", "test_token_abc")


@pytest.fixture()
def wechat_app(wechat_token):
    """Create a minimal FastAPI app with WeChat routes and a mock orchestrator."""
    app = FastAPI()

    class MockOrchestrator:
        async def handle_message(self, msg):
            from open_chat_shop.core.types import AgentMessage

            return AgentMessage(
                message_type="text",
                payload={"content": f"echo: {msg.content}"},
                text_fallback=f"echo: {msg.content}",
            )

    setup_wechat_routes(app, MockOrchestrator())
    return app


@pytest.fixture()
def wechat_client(wechat_app):
    return TestClient(wechat_app)


@pytest.fixture()
def full_config_dir(tmp_path):
    """Create a temp config directory with all required YAML files including channels."""
    providers_yaml = (
        "providers:\n"
        "  - name: openai\n"
        "    type: openai\n"
        "    model: gpt-4o-mini\n"
        "    api_key_env: OPENAI_API_KEY\n"
        "cascade:\n"
        "  levels:\n"
        "    - provider: openai\n"
        "      confidence_threshold: 0.7\n"
        "  fallback_provider: openai\n"
    )
    tool_routing_yaml = (
        "max_tools_per_turn: 5\n"
        "rules:\n"
        "  - intent_patterns: ['*']\n"
        "    tools: ['handoff_to_human']\n"
        "    priority: 0\n"
    )
    security_yaml = (
        "injection_detection:\n"
        "  enabled: true\n"
        "  max_input_length: 2000\n"
        "content_safety:\n"
        "  enabled: true\n"
        "  pii_masking: true\n"
        "auth:\n"
        "  jwt_secret_env: JWT_SECRET_KEY\n"
        "rbac:\n"
        "  roles:\n"
        "    - name: admin\n"
        "      tools: ['*']\n"
    )
    scenarios_yaml = (
        "scenarios:\n"
        "  - name: refund\n"
        "    initial_state: initiated\n"
        "    states: [initiated, completed]\n"
    )
    channels_yaml = (
        "web:\n"
        "  enabled: true\n"
        "  max_message_length: 4096\n"
        "wechat:\n"
        "  enabled: false\n"
        "  max_message_length: 2048\n"
        "miniprogram:\n"
        "  enabled: false\n"
        "  max_message_length: 2048\n"
    )

    for name, content in [
        ("providers.yaml", providers_yaml),
        ("tool_routing.yaml", tool_routing_yaml),
        ("security.yaml", security_yaml),
        ("scenarios.yaml", scenarios_yaml),
        ("channels.yaml", channels_yaml),
    ]:
        (tmp_path / name).write_text(content, encoding="utf-8")

    return str(tmp_path)


# ===================================================================
# TestChannelRegistry
# ===================================================================


@pytest.mark.unit
class TestChannelRegistry:
    """Tests for ChannelRegistry and default_registry."""

    def test_default_registry_has_all_channels(self) -> None:
        registry = default_registry()
        channels = registry.list_channels()
        assert sorted(channels) == ["miniprogram", "web", "wechat"]

    def test_get_adapter_web(self) -> None:
        registry = default_registry()
        adapter = registry.get_adapter("web")
        assert isinstance(adapter, WebAdapter)

    def test_get_adapter_wechat(self) -> None:
        registry = default_registry()
        adapter = registry.get_adapter("wechat")
        assert isinstance(adapter, WechatAdapter)

    def test_get_adapter_miniprogram(self) -> None:
        registry = default_registry()
        adapter = registry.get_adapter("miniprogram")
        assert isinstance(adapter, MiniProgramAdapter)

    def test_get_adapter_unknown_falls_back_to_web(self) -> None:
        registry = default_registry()
        adapter = registry.get_adapter("nonexistent_channel")
        assert isinstance(adapter, WebAdapter)

    def test_register_custom_adapter(self) -> None:
        registry = ChannelRegistry()
        custom = WebAdapter()
        registry.register("custom_channel", custom)
        assert "custom_channel" in registry.list_channels()
        assert registry.get_adapter("custom_channel") is custom


# ===================================================================
# TestChannelConfig
# ===================================================================


@pytest.mark.unit
class TestChannelConfig:
    """Tests for ChannelsFileModel and channel config loading."""

    def test_load_channels_yaml(self, full_config_dir) -> None:
        path = os.path.join(full_config_dir, "channels.yaml")
        result = ConfigLoader.load_channels(path)
        assert isinstance(result, ChannelsFileModel)
        assert result.web.enabled is True
        assert result.web.max_message_length == 4096
        assert result.wechat.enabled is False
        assert result.wechat.max_message_length == 2048
        assert result.miniprogram.enabled is False

    def test_channels_file_model_defaults(self) -> None:
        model = ChannelsFileModel()
        assert model.web.enabled is True
        assert model.web.max_message_length == 4096
        assert model.wechat.enabled is False
        assert model.wechat.app_id_env == "WECHAT_APP_ID"
        assert model.miniprogram.enabled is False
        assert model.miniprogram.app_id_env == "WECHAT_MINIPROGRAM_APP_ID"

    def test_load_all_includes_channels(self, full_config_dir) -> None:
        result = ConfigLoader.load_all(full_config_dir)
        assert "channels" in result
        assert isinstance(result["channels"], ChannelsFileModel)
        assert result["channels"].web.enabled is True


# ===================================================================
# TestWechatWebhook
# ===================================================================


@pytest.mark.unit
class TestWechatWebhook:
    """Tests for WeChat webhook GET verification and POST message handling."""

    def test_verify_signature_valid(self, wechat_client, wechat_token) -> None:
        timestamp = "1234567890"
        nonce = "abc123"
        signature = _make_signature("test_token_abc", timestamp, nonce)
        echostr = "hello_from_wechat"

        resp = wechat_client.get(
            "/api/v1/wechat/callback",
            params={
                "signature": signature,
                "timestamp": timestamp,
                "nonce": nonce,
                "echostr": echostr,
            },
        )
        assert resp.status_code == 200
        assert resp.text == echostr

    def test_verify_signature_invalid(self, wechat_client, wechat_token) -> None:
        resp = wechat_client.get(
            "/api/v1/wechat/callback",
            params={
                "signature": "wrong_signature",
                "timestamp": "1234567890",
                "nonce": "abc123",
                "echostr": "hello",
            },
        )
        assert resp.status_code == 403

    def test_verify_no_token_returns_503(self, monkeypatch) -> None:
        """When WECHAT_TOKEN is not set, GET callback returns 503."""
        monkeypatch.delenv("WECHAT_TOKEN", raising=False)
        app = FastAPI()

        class MockOrchestrator:
            async def handle_message(self, msg):
                pass

        setup_wechat_routes(app, MockOrchestrator())
        client = TestClient(app)

        resp = client.get(
            "/api/v1/wechat/callback",
            params={
                "signature": "anything",
                "timestamp": "1234567890",
                "nonce": "abc123",
                "echostr": "hello",
            },
        )
        assert resp.status_code == 503

    def test_post_message_handles_text(self, wechat_client, wechat_token) -> None:
        timestamp = "1234567890"
        nonce = "abc123"
        signature = _make_signature("test_token_abc", timestamp, nonce)

        xml_body = _wechat_xml("user_123", "gh_abc", "Hello")

        resp = wechat_client.post(
            "/api/v1/wechat/callback",
            content=xml_body.encode("utf-8"),
            params={
                "signature": signature,
                "timestamp": timestamp,
                "nonce": nonce,
            },
            headers={"Content-Type": "application/xml"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/xml"

        # Parse the XML reply and verify structure
        root = ET.fromstring(resp.text)
        to_user = root.find("ToUserName")
        from_user = root.find("FromUserName")
        msg_type = root.find("MsgType")
        content = root.find("Content")

        assert to_user is not None and to_user.text == "user_123"
        assert from_user is not None and from_user.text == "gh_abc"
        assert msg_type is not None and msg_type.text == "text"
        assert content is not None and "echo: Hello" in (content.text or "")
