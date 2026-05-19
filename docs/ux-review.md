# UX Review Report — OpenChatShop

> Reviewer: AI UX/Product/Engineering Review
> Date: 2026-05-20
> Status: 5 Rounds Completed

## Summary

以新用户视角进行了 5 轮迭代审查和修复。从对话完全不可用（CRITICAL 问题阻断核心路径）到 14 个核心场景全部通过。测试套件 740 tests, 0 failures。

---

## Round 1 — CRITICAL Fixes

| Issue | Fix |
|-------|-----|
| 正则 `搜索?` 误匹配 "查" | 改为 `搜索`（去掉 ? 量词） |
| 实体提取完全缺失 | 添加 `_extract_entities()` — 从用户消息提取 order_id, keyword |
| Strategy 直接传空 entities 给工具 | 检测缺失参数 → 返回友好追问 |
| 路由规则 `"*"` 通配符导致意图错路由 | 移除通配符 |
| Mock 数据全英文 | 商品名/地址/物流中文化 |
| WebSocket URL 硬编码 localhost | 改为 `location.host` 动态获取 |

## Round 2 — 用户体验

| Issue | Fix |
|-------|-----|
| 工具返回原始 dict 字符串 | `BaseTool.format_result()` + 各工具自定义格式化 |
| HTML 聊天界面无快速入口 | 添加 5 个快捷按钮 |
| 订单/物流状态英文 | `_STATUS_MAP` 中文映射 |
| ORD- 正则权重过高 | 0.9 → 0.3 |
| Level1 阈值过严 | 0.85 → 0.70 |

## Round 3 — 格式化完善

| Issue | Fix |
|-------|-----|
| 5 个工具缺 format_result | 全部实现中文格式化输出 |
| 错误信息暴露技术细节 | 统一改为友好提示 |

## Round 4 — 意图覆盖率

| Issue | Fix |
|-------|-----|
| "你好" 返回 fallback | 添加 greeting 意图 + 欢迎回复 |
| "查看订单" 不识别 | 扩展 query_order 正则 |
| "我的订单到哪了" 识别错误 | 添加 `订单.{0,4}到哪` 组合规则 |
| "能退款吗" 识别错误 | 提升 check_refund_eligibility 权重 |
| Level1 阈值再次调优 | 0.70 → 0.60 |

## Round 5 — 综合回归

14 个核心场景全部通过：
- 打招呼、查订单、搜商品、物流查询
- 退款、取消订单、修改地址、转人工
- 退款资格查询、订单号缺失引导

---

## 已知遗留（需要产品/架构决策）

| Issue | Why Deferred |
|-------|-------------|
| REST API 无对话上下文追踪 | 需要架构变更 |
| 两套前端并存 (HTML + React) | 需要统一化决策 |
| SSE 用 GET 方法 | 需要前端配合改动 |
| React 前端未集成到主服务 | 需要构建流程决策 |
| 移动端 sidebar 消失丢状态 | 需要 responsive 设计决策 |
| 无会话历史持久化 | 需要存储架构决策 |

## Files Modified

```
main.py                              — 意图规则权重调优、阈值调整、greeting 意图
src/open_chat_shop/core/intent.py    — _extract_entities() 实体提取
src/open_chat_shop/core/strategy.py  — 缺失参数检测、greeting 回复、友好提示
src/open_chat_shop/core/orchestrator.py — 友好化错误信息、format_result 集成
src/open_chat_shop/core/tool.py      — BaseTool.format_result()
src/open_chat_shop/tools/builtin/_mock_data.py — 中文化
src/open_chat_shop/tools/builtin/query_order.py — format_result + 状态映射
src/open_chat_shop/tools/builtin/query_logistics.py — format_result + 状态映射
src/open_chat_shop/tools/builtin/search_product.py — format_result
src/open_chat_shop/tools/builtin/create_refund.py — format_result
src/open_chat_shop/tools/builtin/cancel_order.py — format_result
src/open_chat_shop/tools/builtin/check_refund_eligibility.py — format_result
src/open_chat_shop/tools/builtin/modify_address.py — format_result
src/open_chat_shop/tools/builtin/handoff_to_human.py — format_result
static/index.html                    — WS URL 动态化 + 快捷按钮
frontend/src/hooks/useChat.ts        — WS URL 动态化
tests/unit/test_builtin_tools.py     — 测试断言适配中文化
```
