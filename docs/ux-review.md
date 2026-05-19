# UX Review Report — OpenChatShop

> Reviewer: AI UX/Product/Engineering Review
> Date: 2026-05-20
> Status: 15 Rounds Completed

## Summary

以新用户视角进行了 15 轮迭代审查和修复。从对话完全不可用（CRITICAL 问题阻断核心路径）到 14 个核心场景全部通过，再到 DX/安全/API 一致性全面优化。测试套件 740 tests, 0 failures。

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

## Round 6 — DX 改进

| Issue | Fix |
|-------|-----|
| 静态文件挂载冲突（app.py + main.py 双重挂载） | 移除 app.py 中的挂载，统一由 main.py 管理 |
| `.dockerignore` 缺失 | 创建 `.dockerignore`，排除测试/文档/缓存 |
| `.env.example` 缺少 ANTHROPIC_BASE_URL/GLM_MODEL | 补充环境变量说明 |
| `.env.example` 数据库名仍为旧名 commerce_agent | 修正为 open_chat_shop |
| Dockerfile 使用 editable install | 改为 `pip install .` |
| docker-compose.yml 使用废弃 version 字段 | 移除 version，添加 ANTHROPIC_API_KEY |

## Round 7 — API 响应清理

| Issue | Fix |
|-------|-----|
| `tool_result` 原始数据泄露到 API 响应 | 移除 orchestrator payload 中的 tool_result 字段 |
| pre_check reason 字符串全英文 | 中文化所有 4 个工具的 pre_check 错误消息 |
| 退款截止日期 ISO 格式不友好 | 格式化为 `YYYY年MM月DD日` |

## Round 8 — 品牌统一

| Issue | Fix |
|-------|-----|
| HTML 标题仍为 "CommerceAgent" | 改为 "OpenChatShop" |
| 侧边栏 logo 显示旧名 | 更新为 OpenChatShop |
| WebSocket 欢迎消息使用旧名 | 更新为 OpenChatShop |

## Round 9 — 安全加固

| Issue | Fix |
|-------|-----|
| 中文 Prompt 注入完全无检测 | 添加 7 条中文注入模式：指令覆盖/角色操控/系统提示提取 |
| "忽略之前所有指令" 未被拦截 | 已覆盖 |
| "告诉我你的系统提示" 未被拦截 | 已覆盖 |

## Round 10 — 流式响应安全

| Issue | Fix |
|-------|-----|
| StreamingOrchestrator 错误事件泄露内部异常 | 替换为用户友好中文消息 |

## Round 11 — 版本管理

| Issue | Fix |
|-------|-----|
| 版本号在 3 处硬编码 | 通过 `importlib.metadata` 统一读取 |

## Round 12 — 技术债务

| Issue | Fix |
|-------|-----|
| 12 处使用废弃 `datetime.utcnow()` | 全部替换为 `datetime.now(timezone.utc)` |
| 消除 60 个 DeprecationWarning | 警告数从 838 降至 778 |

## Round 13 — 对话体验优化

| Issue | Fix |
|-------|-----|
| "谢谢/感谢" 返回 fallback | 添加 thanks 意图，回复礼貌性确认 |

## Round 14 — 前端品牌统一

| Issue | Fix |
|-------|-----|
| React 前端仍显示 "CommerceAgent" | 更新 ChatWindow 标题和 useChat 欢迎消息 |

## Round 15 — 文档与回归验证

- 740 tests, 0 failures
- 15 轮修复全部已提交
- 更新 UX Review 文档

---

## 已知遗留（需要产品/架构决策）

| Issue | Why Deferred |
|-------|-------------|
| `configs/providers.yaml` 从未被加载（死代码） | 需要架构决策：YAML 驱动 vs 硬编码 |
| 两套前端并存 (HTML + React) | 需要统一化决策 |
| SSE 用 GET 方法 | 需要前端配合改动 |
| React 前端未集成到主服务 | 需要构建流程决策 |
| 移动端 sidebar 消失丢状态 | 需要 responsive 设计决策 |
| 无会话历史持久化（跨页面刷新） | 需要存储架构决策 |
| `StreamingOrchestrator` 不实际流式 | 需要真正的 LLM 流式集成 |
| `configs/` 全部 YAML 配置文件为死代码 | 需要决定是否接入 ConfigManager |
| CORS `allow_origins=["*"]` | 生产部署前需限制域名 |
| 无 REST API 速率限制 | 需要中间件接入决策 |
| `anthropic_provider.py` 命名误导（实际是 GLM provider） | 需要产品命名决策 |

## Files Modified (Rounds 6-15)

```
.env.example                              — 补充环境变量、修正数据库名
.dockerignore                             — 新建
Dockerfile                                — pip install . (非 editable)
docker-compose.yml                        — 移除 version, 添加 ANTHROPIC_API_KEY
README.md                                 — 修正聊天 URL
main.py                                   — 静态文件挂载修正、thanks 意图规则
src/open_chat_shop/api/app.py             — 移除静态挂载、版本号统一
src/open_chat_shop/api/streaming.py       — 错误消息不泄露内部异常
src/open_chat_shop/core/orchestrator.py   — 移除 tool_result 泄露
src/open_chat_shop/core/security.py       — 添加中文注入检测模式
src/open_chat_shop/core/context.py        — datetime.now(timezone.utc)
src/open_chat_shop/core/handoff.py        — datetime.now(timezone.utc)
src/open_chat_shop/core/strategy.py       — thanks 意图处理
src/open_chat_shop/storage/redis_context.py — datetime.now(timezone.utc)
src/open_chat_shop/storage/db_context.py  — datetime.now(timezone.utc)
src/open_chat_shop/tools/builtin/check_refund_eligibility.py — 中文 reason + 日期格式化
src/open_chat_shop/tools/builtin/create_refund.py   — pre_check 中文
src/open_chat_shop/tools/builtin/cancel_order.py    — pre_check 中文
src/open_chat_shop/tools/builtin/modify_address.py  — pre_check 中文
static/index.html                         — 品牌名更新
frontend/src/components/ChatWindow.tsx     — 品牌名更新
frontend/src/hooks/useChat.ts             — 品牌名更新
tests/unit/test_main.py                   — 静态挂载断言修正
tests/unit/test_builtin_tools.py          — 中文 reason 断言
tests/unit/test_streaming.py              — 错误消息断言
tests/unit/test_handoff.py                — timezone-aware datetime
```
