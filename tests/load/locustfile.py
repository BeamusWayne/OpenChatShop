"""Locust load-test scenarios for OpenChatShop /api/v1/chat endpoint.

Four user classes model different traffic patterns:
  - ChatUser: random messages across 8 intent categories
  - OrderQuerier: focused order-status queries
  - ProductSearcher: focused product-search queries
  - MixedWorkload: weighted mix (70% chat, 20% order, 10% search)

Run:
    locust -f tests/load/locustfile.py --host http://localhost:8000
"""
from __future__ import annotations

import random

from locust import HttpUser, task, between

# ---------------------------------------------------------------------------
# Intent message templates
# ---------------------------------------------------------------------------

_CHAT_MESSAGES = [
    "你好",
    "我想查一下我的订单",
    "有没有笔记本电脑推荐",
    "我的快递到哪了",
    "我想退货",
    "帮我取消订单",
    "修改一下收货地址",
    "有什么优惠活动",
]


class _BaseChatUser(HttpUser):
    """Shared configuration for all chat user classes."""

    abstract = True
    wait_time = between(1, 3)

    def _send_chat(self, content: str) -> None:
        self.client.post(
            "/api/v1/chat",
            json={
                "session_id": f"load-{self.user_id}",
                "content": content,
                "channel": "web",
            },
        )


class ChatUser(_BaseChatUser):
    """Sends random messages covering 8 intent categories."""

    @task
    def send_random_message(self) -> None:
        self._send_chat(random.choice(_CHAT_MESSAGES))


class OrderQuerier(_BaseChatUser):
    """Focused workload: query order status for ORD-001."""

    @task
    def query_order(self) -> None:
        self._send_chat("查询订单 ORD-001 的状态")


class ProductSearcher(_BaseChatUser):
    """Focused workload: search for laptops."""

    @task
    def search_product(self) -> None:
        self._send_chat("帮我搜索笔记本电脑")


class MixedWorkload(_BaseChatUser):
    """Realistic mix: 70% chat, 20% order queries, 10% product search."""

    @task(7)
    def chat(self) -> None:
        self._send_chat(random.choice(_CHAT_MESSAGES))

    @task(2)
    def query_order(self) -> None:
        self._send_chat("查询订单 ORD-001 的状态")

    @task(1)
    def search_product(self) -> None:
        self._send_chat("帮我搜索笔记本电脑")
