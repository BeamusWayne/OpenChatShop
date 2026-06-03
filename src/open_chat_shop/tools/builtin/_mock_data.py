"""Shared mock data for built-in tools.

All tools use dict-based mock data -- no database required.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

CATEGORIES: list[str] = ["electronics", "office", "accessories", "clothing", "home"]

CATEGORY_LABELS: dict[str, str] = {
    "electronics": "数码电子",
    "office": "办公文具",
    "accessories": "配件",
    "clothing": "服装",
    "home": "家居生活",
}

# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

ORDERS: dict[str, dict[str, Any]] = {
    "ORD-001": {
        "order_id": "ORD-001",
        "customer_id": "user-001",
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
        "customer_id": "user-001",
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
        "customer_id": "user-001",
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
        "customer_id": "user-001",
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
        "customer_id": "user-001",
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
    "ORD-006": {
        "order_id": "ORD-006",
        "customer_id": "user-001",
        "status": "pending",
        "items": [
            {"name": "智能手表", "quantity": 1, "price": 1299.00},
            {"name": "手机壳", "quantity": 2, "price": 39.00},
        ],
        "total_amount": 1377.00,
        "created_at": "2026-05-19T11:20:00Z",
        "address": "杭州市西湖区文三路88号",
        "phone": "15800158000",
    },
    "ORD-007": {
        "order_id": "ORD-007",
        "customer_id": "user-001",
        "status": "pending",
        "items": [
            {"name": "空气净化器", "quantity": 1, "price": 2399.00},
        ],
        "total_amount": 2399.00,
        "created_at": "2026-05-20T09:15:00Z",
        "address": "南京市鼓楼区中山北路200号",
        "phone": "15900159001",
    },
    "ORD-008": {
        "order_id": "ORD-008",
        "customer_id": "user-001",
        "status": "processing",
        "items": [
            {"name": "平板电脑", "quantity": 1, "price": 3299.00},
            {"name": "钢化膜", "quantity": 1, "price": 35.00},
        ],
        "total_amount": 3334.00,
        "created_at": "2026-05-16T13:45:00Z",
        "address": "武汉市洪山区光谷大道77号",
        "phone": "18200182000",
    },
    "ORD-009": {
        "order_id": "ORD-009",
        "customer_id": "user-001",
        "status": "processing",
        "items": [
            {"name": "打印机", "quantity": 1, "price": 899.00},
            {"name": "收纳盒", "quantity": 3, "price": 35.00},
        ],
        "total_amount": 1004.00,
        "created_at": "2026-05-17T10:30:00Z",
        "address": "重庆市渝北区金开大道1599号",
        "phone": "18300183000",
    },
    "ORD-010": {
        "order_id": "ORD-010",
        "customer_id": "user-001",
        "status": "shipped",
        "items": [
            {"name": "笔记本电脑", "quantity": 1, "price": 6999.00},
        ],
        "total_amount": 6999.00,
        "created_at": "2026-05-13T08:00:00Z",
        "address": "西安市雁塔区高新路52号",
        "phone": "17600176000",
    },
    "ORD-011": {
        "order_id": "ORD-011",
        "customer_id": "user-001",
        "status": "shipped",
        "items": [
            {"name": "降噪耳机", "quantity": 1, "price": 899.00},
            {"name": "Type-C数据线", "quantity": 2, "price": 19.90},
        ],
        "total_amount": 938.80,
        "created_at": "2026-05-14T15:30:00Z",
        "address": "天津市和平区南京路118号",
        "phone": "17700177000",
    },
    "ORD-012": {
        "order_id": "ORD-012",
        "customer_id": "user-001",
        "status": "delivered",
        "items": [
            {"name": "咖啡机", "quantity": 1, "price": 1599.00},
            {"name": "屏幕保护膜", "quantity": 2, "price": 25.00},
        ],
        "total_amount": 1649.00,
        "created_at": "2026-05-05T14:00:00Z",
        "address": "苏州市姑苏区人民路500号",
        "phone": "15000150000",
    },
    "ORD-013": {
        "order_id": "ORD-013",
        "customer_id": "user-001",
        "status": "refunded",
        "items": [
            {"name": "纯棉T恤", "quantity": 3, "price": 89.00},
        ],
        "total_amount": 267.00,
        "created_at": "2026-04-28T09:00:00Z",
        "address": "长沙市岳麓区麓山南路36号",
        "phone": "15100151000",
    },
    "ORD-014": {
        "order_id": "ORD-014",
        "customer_id": "user-001",
        "status": "cancelled",
        "items": [
            {"name": "显示器", "quantity": 1, "price": 2499.00},
            {"name": "显示器支架", "quantity": 1, "price": 120.00},
        ],
        "total_amount": 2619.00,
        "created_at": "2026-05-08T16:45:00Z",
        "address": "郑州市金水区花园路99号",
        "phone": "15200152000",
    },
    "ORD-015": {
        "order_id": "ORD-015",
        "customer_id": "user-001",
        "status": "shipped",
        "items": [
            {"name": "冲锋衣", "quantity": 1, "price": 459.00},
            {"name": "手机支架", "quantity": 1, "price": 29.00},
            {"name": "快充充电器", "quantity": 1, "price": 69.00},
        ],
        "total_amount": 557.00,
        "created_at": "2026-05-11T12:00:00Z",
        "address": "青岛市市南区香港中路76号",
        "phone": "15300153000",
    },
}

# ---------------------------------------------------------------------------
# Logistics
# ---------------------------------------------------------------------------

LOGISTICS: dict[str, dict[str, Any]] = {
    "ORD-001": {
        "order_id": "ORD-001",
        "carrier": "顺丰速运",
        "tracking_number": "SF1234567890",
        "timeline": [
            {"time": "2026-05-15T11:00:00Z", "status": "picked_up", "location": "上海仓库"},
            {"time": "2026-05-16T03:00:00Z", "status": "in_transit", "location": "上海分拨中心"},
            {"time": "2026-05-16T18:00:00Z", "status": "in_transit", "location": "北京转运中心"},
            {"time": "2026-05-17T08:00:00Z", "status": "out_for_delivery",
             "location": "北京配送站"},
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
    "ORD-010": {
        "order_id": "ORD-010",
        "carrier": "顺丰速运",
        "tracking_number": "SF2345678901",
        "timeline": [
            {"time": "2026-05-13T09:00:00Z", "status": "picked_up", "location": "西安仓库"},
            {"time": "2026-05-14T02:00:00Z", "status": "in_transit", "location": "西安分拨中心"},
            {"time": "2026-05-15T06:00:00Z", "status": "in_transit", "location": "郑州转运中心"},
            {"time": "2026-05-17T10:00:00Z", "status": "in_transit", "location": "西安转运中心"},
            {"time": "2026-05-18T09:30:00Z", "status": "out_for_delivery",
             "location": "雁塔区配送站"},
        ],
    },
    "ORD-011": {
        "order_id": "ORD-011",
        "carrier": "中通快递",
        "tracking_number": "ZT3456789012",
        "timeline": [
            {"time": "2026-05-14T16:30:00Z", "status": "picked_up", "location": "天津仓库"},
            {"time": "2026-05-15T08:00:00Z", "status": "in_transit", "location": "天津分拨中心"},
            {"time": "2026-05-16T11:00:00Z", "status": "in_transit", "location": "和平区营业部"},
            {"time": "2026-05-18T07:30:00Z", "status": "out_for_delivery",
             "location": "南京路配送点"},
        ],
    },
    "ORD-012": {
        "order_id": "ORD-012",
        "carrier": "京东物流",
        "tracking_number": "JD4567890123",
        "timeline": [
            {"time": "2026-05-05T15:00:00Z", "status": "picked_up", "location": "苏州仓库"},
            {"time": "2026-05-06T04:00:00Z", "status": "in_transit", "location": "苏州分拨中心"},
            {"time": "2026-05-06T14:00:00Z", "status": "out_for_delivery",
             "location": "姑苏区配送站"},
            {"time": "2026-05-06T16:30:00Z", "status": "delivered", "location": "姑苏区配送站"},
        ],
    },
    "ORD-015": {
        "order_id": "ORD-015",
        "carrier": "圆通速递",
        "tracking_number": "YT5678901234",
        "timeline": [
            {"time": "2026-05-11T13:00:00Z", "status": "picked_up", "location": "青岛仓库"},
            {"time": "2026-05-12T05:00:00Z", "status": "in_transit", "location": "青岛分拨中心"},
            {"time": "2026-05-14T10:00:00Z", "status": "in_transit", "location": "济南转运中心"},
            {"time": "2026-05-16T18:00:00Z", "status": "in_transit",
             "location": "青岛市南区营业部"},
        ],
    },
    "ORD-008": {
        "order_id": "ORD-008",
        "carrier": "韵达快递",
        "tracking_number": "YD6789012345",
        "timeline": [
            {"time": "2026-05-17T08:00:00Z", "status": "picked_up", "location": "武汉仓库"},
            {"time": "2026-05-17T15:00:00Z", "status": "in_transit", "location": "武汉分拨中心"},
            {"time": "2026-05-18T09:00:00Z", "status": "in_transit", "location": "洪山区营业部"},
        ],
    },
    "ORD-009": {
        "order_id": "ORD-009",
        "carrier": "极兔速递",
        "tracking_number": "JT7890123456",
        "timeline": [
            {"time": "2026-05-17T11:00:00Z", "status": "picked_up", "location": "重庆仓库"},
            {"time": "2026-05-18T03:00:00Z", "status": "in_transit", "location": "重庆分拨中心"},
            {"time": "2026-05-19T06:00:00Z", "status": "in_transit", "location": "渝北区营业部"},
            {"time": "2026-05-20T08:00:00Z", "status": "out_for_delivery",
             "location": "金开大道配送点"},
        ],
    },
}

# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

PRODUCTS: list[dict[str, Any]] = [
    # --- existing P-001 through P-012 (unchanged) ---
    {"id": "P-001", "name": "无线鼠标", "price": 79.00, "category": "electronics", "image_url": "https://example.com/images/mouse.jpg"},
    {"id": "P-002", "name": "USB-C 扩展坞", "price": 149.00, "category": "electronics",
     "image_url": "https://example.com/images/hub.jpg"},
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
    # --- new P-013 through P-030 ---
    # electronics
    {"id": "P-013", "name": "降噪耳机", "price": 899.00, "category": "electronics", "image_url": "https://example.com/images/headphone-anc.jpg"},
    {"id": "P-014", "name": "平板电脑", "price": 3299.00, "category": "electronics", "image_url": "https://example.com/images/tablet.jpg"},
    {"id": "P-015", "name": "笔记本电脑", "price": 6999.00, "category": "electronics", "image_url": "https://example.com/images/laptop.jpg"},
    {"id": "P-016", "name": "快充充电器", "price": 69.00, "category": "electronics", "image_url": "https://example.com/images/charger.jpg"},
    {"id": "P-017", "name": "智能手表", "price": 1299.00, "category": "electronics", "image_url": "https://example.com/images/smartwatch.jpg"},
    # office
    {"id": "P-018", "name": "显示器", "price": 2499.00, "category": "office", "image_url": "https://example.com/images/monitor.jpg"},
    {"id": "P-019", "name": "打印机", "price": 899.00, "category": "office", "image_url": "https://example.com/images/printer.jpg"},
    {"id": "P-020", "name": "收纳盒", "price": 35.00, "category": "office", "image_url": "https://example.com/images/storage-box.jpg"},
    # accessories
    {"id": "P-021", "name": "手机壳", "price": 39.00, "category": "accessories", "image_url": "https://example.com/images/phone-case.jpg"},
    {"id": "P-022", "name": "钢化膜", "price": 35.00, "category": "accessories", "image_url": "https://example.com/images/tempered-glass.jpg"},
    {"id": "P-023", "name": "Type-C数据线", "price": 19.90, "category": "accessories", "image_url": "https://example.com/images/type-c-cable.jpg"},
    {"id": "P-024", "name": "手机支架", "price": 29.00, "category": "accessories", "image_url": "https://example.com/images/phone-holder.jpg"},
    # clothing (new category)
    {"id": "P-025", "name": "纯棉T恤", "price": 89.00, "category": "clothing", "image_url": "https://example.com/images/tshirt.jpg"},
    {"id": "P-026", "name": "冲锋衣", "price": 459.00, "category": "clothing", "image_url": "https://example.com/images/jacket.jpg"},
    {"id": "P-027", "name": "运动卫衣", "price": 199.00, "category": "clothing", "image_url": "https://example.com/images/hoodie.jpg"},
    {"id": "P-028", "name": "休闲牛仔裤", "price": 259.00, "category": "clothing", "image_url": "https://example.com/images/jeans.jpg"},
    # home (new category)
    {"id": "P-029", "name": "咖啡机", "price": 1599.00, "category": "home", "image_url": "https://example.com/images/coffee-maker.jpg"},
    {"id": "P-030", "name": "空气净化器", "price": 2399.00, "category": "home", "image_url": "https://example.com/images/air-purifier.jpg"},
]

# ---------------------------------------------------------------------------
# Refunds (mutable store for write operations)
# ---------------------------------------------------------------------------

REFUNDS: dict[str, dict[str, Any]] = {}
REFUND_COUNTER: int = 0

# ---------------------------------------------------------------------------
# Human handoff
# ---------------------------------------------------------------------------

HANDOFF_RESPONSE: dict[str, Any] = {
    "transferred": True,
    "estimated_wait_seconds": 120,
    "queue_position": 3,
    "message": "正在为您转接人工客服，预计等待时间约2分钟。",
}
