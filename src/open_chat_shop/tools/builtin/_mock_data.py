"""Shared mock data for built-in tools.

All tools use dict-based mock data -- no database required.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

ORDERS: dict[str, dict] = {
    "ORD-001": {
        "order_id": "ORD-001",
        "status": "shipped",
        "items": [
            {"name": "无线鼠标", "quantity": 1, "price": 79.00},
            {"name": "USB-C 扩展坞", "quantity": 1, "price": 149.00},
        ],
        "total_amount": 228.00,
        "created_at": "2026-05-15T10:30:00Z",
        "address": "上海市浦东新区世纪大道123号",
        "phone": "13800138000",
    },
    "ORD-002": {
        "order_id": "ORD-002",
        "status": "pending",
        "items": [
            {"name": "机械键盘", "quantity": 1, "price": 399.00},
        ],
        "total_amount": 399.00,
        "created_at": "2026-05-18T08:00:00Z",
        "address": "北京市朝阳区建国路456号",
        "phone": "13900139000",
    },
    "ORD-003": {
        "order_id": "ORD-003",
        "status": "processing",
        "items": [
            {"name": "显示器支架", "quantity": 2, "price": 120.00},
        ],
        "total_amount": 240.00,
        "created_at": "2026-05-17T14:00:00Z",
        "address": "深圳市南山区科技园789号",
        "phone": "13700137000",
    },
    "ORD-004": {
        "order_id": "ORD-004",
        "status": "refunded",
        "items": [
            {"name": "高清摄像头", "quantity": 1, "price": 199.00},
        ],
        "total_amount": 199.00,
        "created_at": "2026-05-10T09:00:00Z",
        "address": "广州市天河区天河路321号",
        "phone": "13600136000",
    },
    "ORD-005": {
        "order_id": "ORD-005",
        "status": "delivered",
        "items": [
            {"name": "笔记本电脑包", "quantity": 1, "price": 59.00},
            {"name": "屏幕保护膜", "quantity": 2, "price": 25.00},
        ],
        "total_amount": 109.00,
        "created_at": "2026-05-12T16:00:00Z",
        "address": "成都市锦江区红星路654号",
        "phone": "13500135000",
    },
}

# ---------------------------------------------------------------------------
# Logistics
# ---------------------------------------------------------------------------

LOGISTICS: dict[str, dict] = {
    "ORD-001": {
        "order_id": "ORD-001",
        "carrier": "顺丰速运",
        "tracking_number": "SF1234567890",
        "timeline": [
            {"time": "2026-05-15T11:00:00Z", "status": "picked_up", "location": "上海仓库"},
            {"time": "2026-05-16T03:00:00Z", "status": "in_transit", "location": "上海分拨中心"},
            {"time": "2026-05-16T18:00:00Z", "status": "in_transit", "location": "北京转运中心"},
            {"time": "2026-05-17T08:00:00Z", "status": "out_for_delivery", "location": "北京配送站"},
        ],
    },
    "ORD-005": {
        "order_id": "ORD-005",
        "carrier": "京东物流",
        "tracking_number": "JD9876543210",
        "timeline": [
            {"time": "2026-05-12T17:00:00Z", "status": "picked_up", "location": "成都仓库"},
            {"time": "2026-05-13T09:00:00Z", "status": "in_transit", "location": "成都分拨中心"},
            {"time": "2026-05-14T07:00:00Z", "status": "delivered", "location": "成都配送站"},
        ],
    },
}

# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

PRODUCTS: list[dict] = [
    {"id": "P-001", "name": "无线鼠标", "price": 79.00, "category": "electronics", "image_url": "https://example.com/images/mouse.jpg"},
    {"id": "P-002", "name": "USB-C 扩展坞", "price": 149.00, "category": "electronics", "image_url": "https://example.com/images/hub.jpg"},
    {"id": "P-003", "name": "机械键盘", "price": 399.00, "category": "electronics", "image_url": "https://example.com/images/keyboard.jpg"},
    {"id": "P-004", "name": "显示器支架", "price": 120.00, "category": "office", "image_url": "https://example.com/images/stand.jpg"},
    {"id": "P-005", "name": "高清摄像头", "price": 199.00, "category": "electronics", "image_url": "https://example.com/images/webcam.jpg"},
    {"id": "P-006", "name": "笔记本电脑包", "price": 59.00, "category": "accessories", "image_url": "https://example.com/images/sleeve.jpg"},
    {"id": "P-007", "name": "屏幕保护膜", "price": 25.00, "category": "accessories", "image_url": "https://example.com/images/protector.jpg"},
    {"id": "P-008", "name": "LED 台灯", "price": 89.00, "category": "office", "image_url": "https://example.com/images/lamp.jpg"},
    {"id": "P-009", "name": "蓝牙音箱", "price": 129.00, "category": "electronics", "image_url": "https://example.com/images/speaker.jpg"},
    {"id": "P-010", "name": "人体工学椅", "price": 1299.00, "category": "office", "image_url": "https://example.com/images/chair.jpg"},
    {"id": "P-011", "name": "手机", "price": 3999.00, "category": "electronics", "image_url": "https://example.com/images/phone.jpg"},
    {"id": "P-012", "name": "耳机", "price": 299.00, "category": "electronics", "image_url": "https://example.com/images/headphone.jpg"},
]

# ---------------------------------------------------------------------------
# Refunds (mutable store for write operations)
# ---------------------------------------------------------------------------

REFUNDS: dict[str, dict] = {}
REFUND_COUNTER: int = 0

# ---------------------------------------------------------------------------
# Human handoff
# ---------------------------------------------------------------------------

HANDOFF_RESPONSE: dict = {
    "transferred": True,
    "estimated_wait_seconds": 120,
    "queue_position": 3,
    "message": "正在为您转接人工客服，预计等待时间约2分钟。",
}
