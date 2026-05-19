"""Channel Adapter ABC — contracts.md section 6.

Defines the interface that every channel adapter must implement.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from open_chat_shop.core.types import (
    AgentMessage,
    ChannelCapabilities,
    ChannelMessage,
)


class ChannelAdapter(ABC):
    """Base class for channel-specific message adaptation.

    Subclasses must implement:
      - adapt: convert an AgentMessage to a channel-specific ChannelMessage
      - get_capabilities: declare what the channel supports
      - downgrade: produce a safe text-only fallback
    """

    @abstractmethod
    def adapt(self, message: AgentMessage) -> ChannelMessage:
        """Convert *message* to the native format of this channel."""
        ...

    @abstractmethod
    def get_capabilities(self) -> ChannelCapabilities:
        """Return the capabilities of this channel."""
        ...

    @abstractmethod
    def downgrade(self, message: AgentMessage) -> ChannelMessage:
        """Return a text-only fallback when the channel cannot render *message*."""
        ...

    def adapt_with_fallback(self, message: AgentMessage) -> ChannelMessage:
        """Adapt *message*, automatically downgrading if unsupported."""
        if message.message_type in self.get_capabilities().supported_types:
            return self.adapt(message)
        return self.downgrade(message)
