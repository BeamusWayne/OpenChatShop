"""Channel registry — maps channel names to adapter instances."""
from __future__ import annotations

from open_chat_shop.channel.base import ChannelAdapter
from open_chat_shop.channel.miniprogram import MiniProgramAdapter
from open_chat_shop.channel.web import WebAdapter, WechatAdapter


class ChannelRegistry:
    """Maps channel name strings to ChannelAdapter instances."""

    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}

    def register(self, channel: str, adapter: ChannelAdapter) -> None:
        """Register *adapter* under *channel* name."""
        self._adapters[channel] = adapter

    def get_adapter(self, channel: str) -> ChannelAdapter:
        """Return adapter for *channel*, falling back to WebAdapter."""
        return self._adapters.get(channel, WebAdapter())

    def list_channels(self) -> list[str]:
        """Return all registered channel names."""
        return list(self._adapters.keys())


def default_registry() -> ChannelRegistry:
    """Create a registry with all three built-in adapters."""
    registry = ChannelRegistry()
    registry.register("web", WebAdapter())
    registry.register("wechat", WechatAdapter())
    registry.register("miniprogram", MiniProgramAdapter())
    return registry
