"""Channel adapter package."""
from open_chat_shop.channel.base import ChannelAdapter
from open_chat_shop.channel.miniprogram import MiniProgramAdapter
from open_chat_shop.channel.registry import ChannelRegistry, default_registry
from open_chat_shop.channel.web import WebAdapter, WechatAdapter

__all__ = [
    "ChannelAdapter",
    "ChannelRegistry",
    "MiniProgramAdapter",
    "WebAdapter",
    "WechatAdapter",
    "default_registry",
]
