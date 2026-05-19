# 上下文管理器设计

> 依赖契约：[contracts.md](./contracts.md) §1.5 — SessionContext、§1.6 — Slot Tracker 格式

---

## 1. 模块职责

管理每轮对话的上下文状态，确保 LLM 在有限的 Token 预算内获得最相关的信息。

## 2. 组件架构

```
┌─────────────────────────────────────────┐
│            ContextManager               │
│                                          │
│  ┌────────────┐   Token 预算分配器       │
│  │ 滑动窗口    │   ┌─────────────────┐   │
│  │ (最近 N 轮) │   │ System Prompt 20%│   │
│  └────────────┘   │ 对话历史 50%      │   │
│                    │ 工具结果 20%      │   │
│  ┌────────────┐   │ 槽位实体 10%      │   │
│  │ 摘要压缩器  │   └─────────────────┘   │
│  └────────────┘                          │
│                                          │
│  ┌────────────┐   ┌────────────┐        │
│  │ 实体槽位    │   │ 状态快照    │        │
│  │ 追踪器      │   │ 持久化      │        │
│  └────────────┘   └────────────┘        │
└─────────────────────────────────────────┘
```

## 3. 滑动窗口

保留最近 N 轮完整对话。N 的值由 Token 预算动态决定，非固定值。

```
当前 Token 使用 = system_prompt_tokens + history_tokens + slot_tokens

如果 history_tokens > 预算的 50%:
    触发摘要压缩：将窗口外的历史轮次压缩为一条 summary message
```

## 4. 摘要压缩器

当对话历史超出预算时，将旧轮次压缩为摘要：

```python
async def compress(self, messages: list[Message]) -> Message:
    """
    将旧消息列表压缩为一条 system 消息：
    "之前的对话摘要：用户咨询了XX订单的退货问题..."

    压缩比目标：60%
    触发阈值：历史 Token 占用达到预算的 80%
    """
```

## 5. 实体槽位追踪器

维护当前对话中的关键实体，随对话推进更新：

```json
{
  "order_id": "ORD-20260519-001",
  "product_sku": "SKU-888",
  "complaint_type": "quality",
  "refund_amount": null,
  "user_sentiment": "frustrated",
  "intent_confidence": 0.72
}
```

**槽位更新规则：**
- LLM 输出中提取到新实体 → 更新对应槽位
- 工具调用返回的数据 → 填充槽位
- 用户明确否定 → 清除对应槽位
- 场景切换 → 保留通用槽位（user_id），清除场景特定槽位

## 6. Token 预算分配

```yaml
token_budget:
  total: model_max_context - safety_margin
  allocation:
    system_prompt: 20%
    dialogue_history: 50%
    tool_results: 20%
    slot_entities: 10%
  overflow_strategy:
    tool_results_overrun: truncate_oldest_results
    dialogue_overrun: trigger_compression
```

## 7. 状态持久化

```yaml
storage:
  backend: redis
  key_format: "session:{session_id}:context"
  structure: Hash
  ttl: 1800
  snapshot_interval: 5
  recovery: last_snapshot + replay_from_wal
```
