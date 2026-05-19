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
            {"name": "Wireless Mouse", "quantity": 1, "price": 79.00},
            {"name": "USB-C Hub", "quantity": 1, "price": 149.00},
        ],
        "total_amount": 228.00,
        "created_at": "2026-05-15T10:30:00Z",
        "address": "123 Main St, Shanghai",
        "phone": "13800138000",
    },
    "ORD-002": {
        "order_id": "ORD-002",
        "status": "pending",
        "items": [
            {"name": "Mechanical Keyboard", "quantity": 1, "price": 399.00},
        ],
        "total_amount": 399.00,
        "created_at": "2026-05-18T08:00:00Z",
        "address": "456 Oak Ave, Beijing",
        "phone": "13900139000",
    },
    "ORD-003": {
        "order_id": "ORD-003",
        "status": "processing",
        "items": [
            {"name": "Monitor Stand", "quantity": 2, "price": 120.00},
        ],
        "total_amount": 240.00,
        "created_at": "2026-05-17T14:00:00Z",
        "address": "789 Pine Rd, Shenzhen",
        "phone": "13700137000",
    },
    "ORD-004": {
        "order_id": "ORD-004",
        "status": "refunded",
        "items": [
            {"name": "Webcam HD", "quantity": 1, "price": 199.00},
        ],
        "total_amount": 199.00,
        "created_at": "2026-05-10T09:00:00Z",
        "address": "321 Elm Blvd, Guangzhou",
        "phone": "13600136000",
    },
    "ORD-005": {
        "order_id": "ORD-005",
        "status": "delivered",
        "items": [
            {"name": "Laptop Sleeve", "quantity": 1, "price": 59.00},
            {"name": "Screen Protector", "quantity": 2, "price": 25.00},
        ],
        "total_amount": 109.00,
        "created_at": "2026-05-12T16:00:00Z",
        "address": "654 Maple Ln, Chengdu",
        "phone": "13500135000",
    },
}

# ---------------------------------------------------------------------------
# Logistics
# ---------------------------------------------------------------------------

LOGISTICS: dict[str, dict] = {
    "ORD-001": {
        "order_id": "ORD-001",
        "carrier": "SF Express",
        "tracking_number": "SF1234567890",
        "timeline": [
            {"time": "2026-05-15T11:00:00Z", "status": "picked_up", "location": "Shanghai Warehouse"},
            {"time": "2026-05-16T03:00:00Z", "status": "in_transit", "location": "Shanghai Sorting Center"},
            {"time": "2026-05-16T18:00:00Z", "status": "in_transit", "location": "Beijing Distribution Center"},
            {"time": "2026-05-17T08:00:00Z", "status": "out_for_delivery", "location": "Beijing Delivery Station"},
        ],
    },
    "ORD-005": {
        "order_id": "ORD-005",
        "carrier": "JD Logistics",
        "tracking_number": "JD9876543210",
        "timeline": [
            {"time": "2026-05-12T17:00:00Z", "status": "picked_up", "location": "Chengdu Warehouse"},
            {"time": "2026-05-13T09:00:00Z", "status": "in_transit", "location": "Chengdu Sorting Center"},
            {"time": "2026-05-14T07:00:00Z", "status": "delivered", "location": "Chengdu Delivery Station"},
        ],
    },
}

# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

PRODUCTS: list[dict] = [
    {"id": "P-001", "name": "Wireless Mouse", "price": 79.00, "category": "electronics", "image_url": "https://example.com/images/mouse.jpg"},
    {"id": "P-002", "name": "USB-C Hub", "price": 149.00, "category": "electronics", "image_url": "https://example.com/images/hub.jpg"},
    {"id": "P-003", "name": "Mechanical Keyboard", "price": 399.00, "category": "electronics", "image_url": "https://example.com/images/keyboard.jpg"},
    {"id": "P-004", "name": "Monitor Stand", "price": 120.00, "category": "office", "image_url": "https://example.com/images/stand.jpg"},
    {"id": "P-005", "name": "Webcam HD", "price": 199.00, "category": "electronics", "image_url": "https://example.com/images/webcam.jpg"},
    {"id": "P-006", "name": "Laptop Sleeve", "price": 59.00, "category": "accessories", "image_url": "https://example.com/images/sleeve.jpg"},
    {"id": "P-007", "name": "Screen Protector", "price": 25.00, "category": "accessories", "image_url": "https://example.com/images/protector.jpg"},
    {"id": "P-008", "name": "Desk Lamp LED", "price": 89.00, "category": "office", "image_url": "https://example.com/images/lamp.jpg"},
    {"id": "P-009", "name": "Bluetooth Speaker", "price": 129.00, "category": "electronics", "image_url": "https://example.com/images/speaker.jpg"},
    {"id": "P-010", "name": "Ergonomic Chair", "price": 1299.00, "category": "office", "image_url": "https://example.com/images/chair.jpg"},
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
    "message": "Transferring to human agent. Estimated wait time: ~2 minutes.",
}
