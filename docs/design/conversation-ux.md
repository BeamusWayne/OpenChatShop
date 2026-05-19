# 对话体验设计

> 依赖契约：[contracts.md](./contracts.md) §5 — ChannelAdapter 接口、§7 — 消息类型清单

---

## 1. 产品形态

OpenChatShop 以 **Web 为首要交付形态**，通过 Channel Adapter 支持多渠道。

| 渠道 | 接入方式 | 消息能力 | 优先级 |
|------|---------|---------|--------|
| **Web** | 嵌入式 Chat Widget (JS SDK) | 全部 | P0 |
| **APP 内嵌** | React Native / Flutter SDK | 全部 | P1 |
| **微信公众号** | 消息回调 + 模板消息 | 受限：文本、图文链接 | P1 |
| **微信小程序** | 内嵌 WebView / 原生组件 | 大部分 | P2 |
| **开放 API** | REST + WebSocket | 无限制 | P0 |

## 2. 渠道降级规则

不同渠道消息能力不同，通过 ChannelAdapter 自动降级：

| 消息类型 | Web | 微信公众号 | 微信小程序 | 纯文本 |
|---------|-----|-----------|-----------|--------|
| product_card | 原生卡片 | 图文链接 | 简化卡片 | 商品名 + 价格 + URL |
| confirm | 弹窗 | 回复 1/2 | 弹窗 | 回复 Y/N |
| logistics_timeline | 时间线 | 文本列表 | 时间线 | 文本描述 |
| form | 内嵌表单 | 不支持 → 引导到 H5 | 简化表单 | 文本引导输入 |
| rating | 星级组件 | 不支持 → 追问 | 星级组件 | "1-5分请回复" |

## 3. Web Chat Widget

### 3.1 接入方式

```html
<script src="https://cdn.jsdelivr.net/npm/@open-chat-shop/web-widget"></script>
<script>
  OpenChatShop.init({
    apiUrl: 'https://your-agent-api.com',
    channel: 'web',
    theme: {
      primaryColor: '#6366f1',
      position: 'bottom-right',
      locale: 'zh-CN'
    }
  });
</script>
```

### 3.2 交互布局

```
+----------------------------------+
|  客服助手              - [ ] x   |  可拖拽、可折叠
+----------------------------------+
|                                  |
|  您好！请问有什么可以帮您？       |  欢迎语（可配置）
|                                  |
|  [查询订单] [商品推荐] [退换货]  |  快捷入口（场景驱动）
|                                  |
+----------------------------------+
|  请输入您的问题...         + >   |  支持图片上传
+----------------------------------+
```

### 3.3 会话状态指示

| 状态 | 显示 |
|------|------|
| 在线 | Agent 正常服务 |
| 思考中 | "正在思考..." + 打字动画 |
| 处理中 | "正在查询订单信息..." + 进度条 |
| 已转人工 | 坐席名称 + 头像 |
| 已结束 | 满意度评分入口 |

## 4. 消息 payload 示例

```json
{
  "message_type": "product_card",
  "payload": {
    "product_id": "SKU-888",
    "name": "无线蓝牙耳机 Pro",
    "price": 299.00,
    "image_url": "https://...",
    "rating": 4.7,
    "stock": 126,
    "actions": [
      {"type": "add_to_cart", "label": "加入购物车"},
      {"type": "view_detail", "label": "查看详情"}
    ]
  }
}
```

## 5. 体验指标

| 指标 | 目标值 | 度量方式 |
|------|--------|---------|
| 首次响应时间 | < 1s | 流式首 Token 时间 |
| 端到端响应时间 | P99 < 3s | 用户发送到完整回复 |
| 打字中断率 | < 5% | 用户在 Agent 回复中发送新消息 |
| 快捷入口点击率 | > 30% | 用户使用快捷按钮比例 |
| 会话完成率 | > 85% | 用户问题被解决，未转人工 |
| 满意度评分 | >= 4.2/5 | 会话结束评分 |
