# OpenChatShop

模型无关的开源电商智能对话系统。通过统一的 LLM Provider 抽象层，一套代码适配 OpenAI、Anthropic、Qwen、DeepSeek、Ollama 等任意大语言模型后端，快速搭建生产级电商客服 Agent。

## 核心特性

- **模型无关** — Provider 抽象层解耦 LLM 依赖，YAML 配置切换模型，无需改代码
- **三级意图级联** — 规则匹配 → 语义检索 → LLM 分类，按置信度逐级升级
- **可插拔工具系统** — 8 个内置电商工具（订单/物流/商品/退款/转人工），自定义工具只需继承 `BaseTool`
- **富消息渲染** — 订单卡片、物流时间线、商品网格、转接状态 4 种富消息组件，前端按 `messageType` 自动渲染
- **人工客服后台** — 独立坐席管理界面，三栏布局（会话列表/聊天/客户信息），WebSocket 实时通知，自动分配
- **四层安全防护** — Prompt 注入检测、内容安全过滤、RBAC 权限校验、输出脱敏
- **业务状态机** — 售前咨询/售后处理/退款流程独立 FSM，可编排组合
- **多渠道适配** — Web、微信公众号、微信小程序统一接口，按渠道自动路由，11 种富消息类型渲染
- **Repository 层** — 5 个 Repository ABC（Order/Product/Logistics/Refund/Handoff），零配置内存模式 + 设 DATABASE_URL 自动切换数据库，工具层与存储完全解耦
- **弹性容错** — 熔断器（Circuit Breaker）+ 指数退避重试保护 LLM 调用，Redis/内存双模式限速器，读操作响应缓存
- **可观测性** — Prometheus 指标 + Grafana 仪表盘 + OpenTelemetry 链路追踪 + 结构化审计日志
- **生产就绪** — JWT/API Key 认证、速率限制、成本治理、会话持久化、Docker 多阶段构建、CI/CD、安全响应头、就绪探针

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+（可选，用于前端富消息渲染和人工客服后台）

### 安装

```bash
git clone https://github.com/BeamusWayne/OpenChatShop.git
cd OpenChatShop
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .
```

### 启动服务

```bash
# 最简启动（内存模式 + 纯规则引擎，无需 API Key）
./run.sh
```

> 无需任何配置即可体验完整对话功能。系统内置规则引擎处理订单查询、商品搜索、物流追踪、退款、转人工等场景。
>
> 如果已安装 Node.js，`./run.sh` 会自动构建前端（首次较慢），提供富消息卡片渲染。
> 未安装 Node.js 时，使用内置的纯文本聊天界面，功能不受影响。

服务启动后访问：
- 聊天界面: http://localhost:8000/
- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health
- 就绪探针: http://localhost:8000/health/ready
- Prometheus 指标: http://localhost:8000/metrics

### 启动人工客服后台

人工客服后台是独立的前端应用，需要 Node.js：

```bash
# 先启动后端（新终端）
./run.sh

# 启动坐席后台
cd frontend-agent
npm install
npm run dev
```

访问 http://localhost:5174/ ，输入坐席名称即可进入三栏管理界面。

坐席后台功能：
- 排队列表实时更新（WebSocket 推送）
- 一键接入客户会话
- 双向实时聊天
- 客户信息面板
- 结束服务
- 后端重启后自动重连并注册（无需重新登录）

### 配置 LLM Provider（可选）

默认使用规则引擎，无需 LLM。如需接入大模型提升智能度：

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

### 配置数据库（可选）

默认使用内存模式（mock 数据），无需数据库。如需数据持久化：

```bash
# .env 中添加：
DATABASE_URL=sqlite:///data/shop.db        # SQLite（最简单）
# DATABASE_URL=postgresql://user:pass@localhost:5432/shop  # PostgreSQL（生产推荐）
```

首次启动自动建表并从 mock 数据集初始化。重启后数据不丢失。

支持的环境变量：

| 变量 | 说明 | 必填 |
|------|------|------|
| `ANTHROPIC_API_KEY` | Anthropic / 智谱 GLM API Key | 接入 LLM 时必填 |
| `ANTHROPIC_BASE_URL` | 自定义 API 端点（默认 Anthropic 官方） | 否 |
| `GLM_MODEL` | 模型名称（默认 glm-5.1） | 否 |
| `OPENAI_API_KEY` | OpenAI API Key | 否 |
| `DATABASE_URL` | 数据库连接串（SQLite/PostgreSQL） | 数据持久化时必填 |
| `REDIS_URL` | Redis 连接串（限速器 + 缓存 + 会话持久化） | 否 |
| `WECHAT_APP_ID` | 微信公众号 AppID | 接入公众号时必填 |
| `WECHAT_APP_SECRET` | 微信公众号 AppSecret | 接入公众号时必填 |
| `WECHAT_TOKEN` | 微信公众号 Token | 接入公众号时必填 |
| `WECHAT_ENCODING_AES_KEY` | 微信公众号 EncodingAESKey | 否 |
| `WECHAT_MINIPROGRAM_APP_ID` | 微信小程序 AppID | 接入小程序时必填 |
| `WECHAT_MINIPROGRAM_APP_SECRET` | 微信小程序 AppSecret | 接入小程序时必填 |
| `WECHAT_MINIPROGRAM_TOKEN` | 微信小程序 Token | 接入小程序时必填 |
| `API_KEY` | 静态 API Key（与 JWT 二选一） | 否 |
| `CORS_ORIGINS` | 允许的跨域来源（逗号分隔，默认 localhost:3000,localhost:8000） | 否 |
| `JWT_SECRET_KEY` | JWT 签名密钥 | 否 |
| `LOG_LEVEL` | 日志级别（默认 INFO） | 否 |

### Docker Compose

```bash
# 完整部署（api + postgres + redis + prometheus + grafana）
docker compose up
```

| 服务 | 端口 | 说明 |
|------|------|------|
| agent-api | 8000 | 主 API 服务 |
| postgres | 5432 (内部) | 数据库（pgvector） |
| redis | 6379 (内部) | 缓存 + 限速 + 会话 |
| prometheus | 9090 | 指标采集 |
| grafana | 3000 | 监控仪表盘（admin/admin） |

## 弹性与容错

### 熔断器

LLM 调用受 Circuit Breaker 保护，避免级联故障：

```
CLOSED →（连续 5 次失败）→ OPEN →（30 秒后）→ HALF_OPEN →（探针成功）→ CLOSED
                                                         └→（探针失败）→ OPEN
```

- `failure_threshold=5` — 连续失败 5 次触发熔断
- `recovery_timeout=30s` — 熔断 30 秒后进入半开状态
- 半开状态允许 1 个探针请求验证恢复

### 重试策略

瞬态错误（TimeoutError、ConnectionError、OSError）自动重试：

- `max_retries=3` — 最多重试 3 次
- 指数退避：1s → 2s → 4s（上限 8s）
- 业务错误（ValueError 等）不重试，立即抛出

### 响应缓存

读操作（商品搜索、订单查询、物流查询）自动缓存，减少 LLM 调用：

| 意图 | TTL | 后端 |
|------|-----|------|
| `search_product` | 5 分钟 | Redis / 内存 |
| `query_order` | 1 分钟 | Redis / 内存 |
| `query_logistics` | 30 秒 | Redis / 内存 |

写操作（退款、取消订单、修改地址、转人工）不缓存。设 `REDIS_URL` 自动启用分布式缓存，否则使用进程内缓存。

### 速率限制

滑动窗口算法，支持 Redis 和内存双后端：

| 维度 | 窗口 | 上限 |
|------|------|------|
| 用户消息 | 60 秒 | 30 条 |
| IP 请求 | 60 秒 | 60 条 |
| 工具调用 | 3600 秒 | 1000 次 |

设 `REDIS_URL` 自动使用 Redis 分布式限速（Lua 原子脚本），否则进程内限速。

## 监控与可观测性

### Prometheus 指标

`/metrics` 端点暴露以下指标：

| 指标 | 类型 | 说明 |
|------|------|------|
| `openchatshop_chat_requests_total` | Counter | 聊天请求总数（按 intent/status 分维） |
| `openchatshop_chat_duration_seconds` | Histogram | 聊天请求延迟（分桶 0.1s-10s） |
| `openchatshop_llm_calls_total` | Counter | LLM 调用次数（按 model/status） |
| `openchatshop_llm_tokens_total` | Counter | Token 消耗（按 model/type） |
| `openchatshop_tool_calls_total` | Counter | 工具调用次数（按 tool/status） |
| `openchatshop_cache_hits_total` | Counter | 缓存命中次数（按 intent） |
| `openchatshop_active_sessions` | Gauge | 当前活跃会话数 |
| `openchatshop_handoff_queue_size` | Gauge | 人工转接排队数 |

### Grafana 仪表盘

`docker compose up` 后访问 http://localhost:3000 ，内置预配置仪表盘：

- 请求量 & 延迟分布
- LLM 调用成功率 & Token 消耗
- 工具调用频率
- 缓存命中率
- 活跃会话 & 排队趋势

### Prometheus 告警规则

`monitoring/prometheus/alerts.yml` 预定义 3 条告警：

| 告警 | 条件 |
|------|------|
| HighErrorRate | 5 分钟内错误率 > 10% |
| HighLatency | P95 延迟 > 5 秒 |
| LLMProviderDown | LLM 调用连续 2 分钟失败 |

### 健康检查

| 端点 | 用途 |
|------|------|
| `GET /health` | 存活探针（总是返回 ok） |
| `GET /health/ready` | 就绪探针（检查 DB + Redis 连通性，不健康时返回 503） |

### 安全响应头

所有 HTTP 响应自动添加安全头：

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy: default-src 'self'`
- HTTPS 时自动添加 `Strict-Transport-Security`

## CI/CD

GitHub Actions 自动化流水线（`.github/workflows/ci.yml`）：

| Job | 说明 |
|-----|------|
| lint | Ruff 代码规范检查 |
| type-check | MyPy 类型检查 |
| test | pytest 测试（Python 3.11 + 3.12 矩阵） |
| frontend | 前端构建验证 |
| docker | Docker 镜像构建验证 |

5 个 Job 并行执行，PR 自动触发。

## 负载测试

使用 Locust 进行压力测试：

```bash
pip install -e ".[dev]"
cd tests/load
locust -f locustfile.py --host=http://localhost:8000
```

访问 http://localhost:8089 查看 Locust 控制台。

内置 4 种测试场景：
- `ChatUser` — 基础对话（问候/感谢）
- `OrderUser` — 订单查询
- `ProductUser` — 商品搜索
- `WebSocketUser` — WebSocket 连接

## 富消息渲染

前端根据消息角色（`role`）和 `messageType` 渲染不同样式：

| 角色 | 头像 | 样式 | 来源 |
|------|------|------|------|
| `assistant` | 机器人（橙色） | 白底边框气泡 | AI 回复 |
| `agent` | 客服（蓝色）+ 客服名称 | 蓝底气泡 | 人工客服回复 |
| `system` | 无头像 | 居中灰底 | 系统通知 |
| `user` | 用户（主题色） | 主题色气泡 | 用户消息 |

根据后端返回的 `messageType` 自动渲染对应的富消息卡片：

| messageType | 组件 | 触发场景 |
|-------------|------|---------|
| `order_card` | OrderCard | 查询订单 → 订单号、商品、金额、状态标签 |
| `logistics_timeline` | LogisticsTimeline | 物流查询 → 物流商、运单号、轨迹时间线 |
| `product_list` | ProductGrid | 搜索商品 → 商品卡片网格（图片、名称、价格） |
| `transfer` | TransferStatus | 转人工 → 排队位置、预计等待、坐席接入通知 |

示例对话：

```
用户: "查询订单 ORD-001"
AI: [订单卡片] ORD-001 | 无线鼠标+扩展坞 | ¥228 | 已发货

用户: "物流查询"
AI: [物流时间线] 顺丰速运 SF1234567890
     ● 已发货 (05-15 14:30)
     ● 运输中 (05-16 08:00)
     ○ 派送中

用户: "搜索手机"
AI: [商品网格] 手机 ¥4999 | 蓝牙音箱 ¥199 | ...

用户: "转人工"
AI: [转接状态] 正在为您转接... 排队第 2 位，预计等待 3 分钟
```

> 富消息需要 React 前端（需 Node.js 构建）。未安装 Node.js 时，所有消息以纯文本呈现。

## 人工转接

### 会话模式状态机

系统通过 `SessionMode` 状态机管理 AI 与人工客服的切换：

```
AI_MODE ──(用户请求转人工)──→ TRANSFER_PENDING ──(坐席接入)──→ HUMAN_MODE
   ↑                                                            │
   └────────────────────(坐席结束服务)──────────────────────────┘
```

- **AI_MODE**：智能助手处理所有消息，客户可使用快捷操作
- **TRANSFER_PENDING**：AI 静默，显示排队位置和预计等待
- **HUMAN_MODE**：AI 完全静默，客户消息直接转发给坐席，前端切换为人工客服 UI

客户端根据 mode 切换：
- Header：机器人头像/转接中/客服头像
- 快捷操作：AI 模式显示，人工模式隐藏
- 消息气泡：AI 消息用机器人图标（橙色），客服消息用客服图标（蓝色）+ 客服名称
- 输入框：placeholder 从"输入消息"变为"发送给客服"

### 端到端流程

```
客户: "转人工" → 后端排队 → 自动分配空闲坐席 → 双方 WebSocket 实时通信
                                           ↓ 无空闲坐席
                                    显示排队位置 + 预计等待
```

### Agent API

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/v1/agent/register` | POST | 坐席注册 |
| `/api/v1/agent/agents` | GET | 在线坐席列表 |
| `/api/v1/agent/{id}/status` | PUT | 更新坐席状态 |
| `/api/v1/agent/queue` | GET | 排队列表 |
| `/api/v1/agent/active` | GET | 进行中的会话 |
| `/api/v1/agent/accept/{session_id}` | POST | 接入排队会话 |
| `/api/v1/agent/complete/{session_id}` | POST | 结束人工服务 |

### Agent WebSocket

`ws://localhost:8000/ws/agent/{agent_id}`

服务端推送事件：
- `queue_state` — 连接后发送当前队列
- `new_request` — 新客户排队
- `request_assigned` — 会话已分配
- `session_history` — 坐席接入时推送 AI 对话历史
- `customer_message` — 客户发来的消息（HUMAN_MODE 下）
- `transfer_completed` — 会话已结束

客户端发送事件：
- `agent_message` — 坐席回复客户
- `heartbeat` — 心跳保活

## 多渠道接入

系统内置三个渠道适配器，通过 `ChannelRegistry` 按请求中的 `channel` 字段自动路由到对应适配器，无需手动选择。

### 渠道概览

| 渠道 | Adapter | 支持消息类型 | 接入方式 |
|------|---------|-------------|---------|
| **Web** | `WebAdapter` | 11 种（全量） | 开箱即用 |
| **微信公众号** | `WechatAdapter` | 3 种，其余自动降级为文本 | 配置 `.env` 后可用 |
| **微信小程序** | `MiniProgramAdapter` | 6 种，其余自动降级为文本 | 配置 `.env` 后可用 |

### 消息类型对照

| 消息类型 | Web | 公众号 | 小程序 |
|---------|-----|--------|--------|
| text | ✅ | ✅ | ✅ |
| product_card | ✅ | ✅ | ✅ |
| product_list | ✅ | ❌→文本 | ❌→文本 |
| order_card | ✅ | ✅ | ✅ |
| logistics_timeline | ✅ | ❌→文本 | ✅ |
| confirm | ✅ | ❌→文本 | ❌→文本 |
| form | ✅ | ❌→文本 | ❌→文本 |
| rating | ✅ | ❌→文本 | ✅ |
| transfer | ✅ | ❌→文本 | ❌→文本 |
| carousel | ✅ | ❌→文本 | ❌→文本 |
| quick_replies | ✅ | ❌→文本 | ✅ |

> ❌→文本 表示该渠道不支持此类型，系统自动降级为纯文本回复（`text_fallback`）。

### 接入微信公众号

1. 在 `.env` 中配置微信变量：

```bash
WECHAT_APP_ID=你的公众号AppID
WECHAT_APP_SECRET=你的公众号AppSecret
WECHAT_TOKEN=你设定的Token
WECHAT_ENCODING_AES_KEY=你的EncodingAESKey
```

2. 登录 [微信公众平台](https://mp.weixin.qq.com) → 开发 → 基本配置 → 服务器地址填入：

```
https://your-domain/api/v1/wechat/callback
```

3. 微信服务器会发送 GET 请求验签，通过后即可接收用户消息并自动回复。

### 接入微信小程序

1. 在 `.env` 中配置小程序变量：

```bash
WECHAT_MINIPROGRAM_APP_ID=你的小程序AppID
WECHAT_MINIPROGRAM_APP_SECRET=你的小程序AppSecret
WECHAT_MINIPROGRAM_TOKEN=你设定的Token
```

2. 小程序前端通过 REST API 发送消息，设置 `channel: "miniprogram"`：

```javascript
const res = await fetch('/api/v1/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    session_id: userId,
    content: '搜索手机',
    channel: 'miniprogram',
  }),
});
```

### 自定义渠道

继承 `ChannelAdapter` 并注册到 Registry：

```python
from open_chat_shop.channel.base import ChannelAdapter
from open_chat_shop.channel.registry import default_registry

class MyChannelAdapter(ChannelAdapter):
    # 实现 adapt(), get_capabilities(), downgrade()
    ...

registry = default_registry()
registry.register("my_channel", MyChannelAdapter())
```

### 渠道配置文件

渠道相关配置在 `configs/channels.yaml`，可控制每个渠道的启用状态和消息长度限制。

## 系统架构

### 分层架构

```
┌──────────────────────────────────────────────────────────┐
│                      渠道层 (Channel)                      │
│  WebAdapter  ·  WechatAdapter  ·  MiniProgramAdapter      │
│            ChannelRegistry · 自动路由 · 降级兜底            │
├──────────────────────────────────────────────────────────┤
│                      API 层 (FastAPI)                      │
│     REST / SSE 流式 / WebSocket / 微信 Webhook             │
│     Agent REST API / Agent WebSocket                       │
│     Prometheus /metrics · SecurityHeaders                  │
├──────────────────────────────────────────────────────────┤
│                    对话编排层 (Orchestrator)                 │
│  Security → Context → Intent → Tool → Strategy → Action   │
├──────────┬──────────┬──────────┬──────────────────────────┤
│ 安全防护  │ 意图引擎  │ 工具系统  │ 对话策略                  │
│ 注入检测  │ 规则匹配  │ 动态注入  │ 状态机 FSM                │
│ PII 脱敏  │ 语义检索  │ 生命周期  │ 槽位追踪                  │
│ RBAC 权限 │ LLM 分类  │ 补偿回滚  │ 人工转接                  │
├──────────┴──────────┴──────────┴──────────────────────────┤
│               弹性层 (Resilience)                          │
│  CircuitBreaker · RetryPolicy · ResponseCache              │
│  RedisRateLimiter · SessionBudgetManager                   │
├──────────────────────────────────────────────────────────┤
│               Repository 抽象层（构造器注入）                │
│  OrderRepository  ·  ProductRepository  ·  LogisticsRepo   │
│  RefundRepository ·  HandoffRepository                      │
│  InMemory（默认） ·  Database（DATABASE_URL）               │
├──────────────────────────────────────────────────────────┤
│                 LLM Provider 抽象层                        │
│  Anthropic · OpenAI · Qwen · DeepSeek · Ollama            │
│  CascadeStrategy · LiteLLM · 级联降级                      │
├──────────────────────────────────────────────────────────┤
│                  基础设施层 (Infrastructure)                 │
│  会话存储    │  可观测性          │  治理                    │
│  内存/Redis  │  Prometheus+Grafana│  速率限制                │
│  SQLModel DB │  链路追踪(OTel)    │  成本治理                │
│  向量检索    │  审计日志(DB)      │  预算管控                │
│              │  CostTracker(DB)   │  CI/CD(GitHub Actions)  │
└──────────────────────────────────────────────────────────┘
```

### 前端架构

```
frontend/                    客户聊天界面（React + Ant Design）
├── src/hooks/
│   └── useChat.ts          聊天 hook + sessionMode 状态机
├── src/components/
│   ├── ChatWindow.tsx       聊天主窗口（按 mode 切换 UI）
│   ├── MessageBubble.tsx    消息气泡（AI/客服/系统三种样式）
│   └── rich/                富消息组件
│       ├── OrderCard.tsx    订单卡片
│       ├── LogisticsTimeline.tsx  物流时间线
│       ├── ProductGrid.tsx  商品网格
│       └── TransferStatus.tsx  转接状态

frontend-agent/              坐席管理后台（独立 React 应用）
├── src/hooks/
│   └── useAgent.ts          Agent WebSocket + REST API hook
├── src/pages/
│   ├── LoginPage.tsx        坐席注册
│   └── DashboardPage.tsx    三栏管理界面
├── src/components/
│   ├── ConversationList.tsx 排队/进行中/已结束
│   ├── AgentChat.tsx        坐席聊天窗口
│   └── CustomerPanel.tsx    客户信息面板
```

### 数据流

一条用户消息从接收到回复经过以下完整链路：

```
用户消息 "ORD-001 物流到哪了"
│
├─ 1. API 接入
│     POST /api/v1/chat {channel: "wechat", content: "ORD-001 物流到哪了"}
│     → ChannelRegistry.get_adapter("wechat")
│     → 构建 UserMessage(session_id, content, channel)
│
├─ 2. 安全检查
│     SecurityGuard.check_input()
│     ├─ PromptInjectionDetector → 正则 + 启发式检测注入攻击
│     ├─ ContentSafetyFilter → PII 脱敏（身份证/手机号/银行卡）
│     └─ PermissionChecker → RBAC 权限校验
│
├─ 3. 上下文加载
│     ContextManager.load(session_id, channel)
│     → 加载历史会话 SessionContext（history, slots, fsm_state）
│     → Token 预算分配：20% 系统 / 50% 历史 / 20% 工具 / 10% 槽位
│
├─ 4. 意图识别（三级级联）
│     CascadeIntentEngine.classify()
│     ├─ Level 1: RuleBasedMatcher → 正则加权匹配（置信度 ≥ 0.85 直接返回）
│     ├─ Level 2: 语义检索 → Jaccard 词重叠（置信度 ≥ 0.70）
│     ├─ Level 3: LLM 分类 → 大模型判断（置信度 ≥ 0.50）
│     └─ Fallback: 未识别意图
│     → 结果: Intent(name="query_logistics", confidence=0.92)
│     → 实体提取: {order_id: "ORD-001"}
│
├─ 4.5 响应缓存查询
│     ResponseCache.get("query_logistics", {order_id: "ORD-001"})
│     → 命中 → 直接返回缓存 AgentMessage，跳过后续步骤
│     → 未命中 → 继续
│
├─ 5. 工具注入
│     ToolInjector.inject(intent, context)
│     ├─ 意图匹配: intent_patterns glob 匹配
│     ├─ 场景过滤: 当前 FSM 状态限制可用工具
│     ├─ 权限过滤: user_role vs required_roles
│     └─ 数量截断: max_tools_per_turn
│     → 结果: [query_logistics]
│
├─ 6. 策略决策
│     RuleBasedStrategy.decide(intent, context, tools)
│     → 检查参数完整性 → 缺失则 clarify
│     → 检查需确认操作 → confirm
│     → 结果: Action(type="tool_call", tool="query_logistics", params={order_id: "ORD-001"})
│
├─ 7. 工具执行
│     BaseTool 生命周期:
│     validate(params) → pre_check → execute → format_result
│     失败时: compensate() 回滚
│     → 结果: ToolResult(logistics=顺丰速运, 3个轨迹点)
│
├─ 8. 响应构建
│     ToolResponseMapper → 构建 AgentMessage(message_type="logistics_timeline")
│     LLM Enhancement (Circuit Breaker + Retry 保护) → 自然语言润色
│
├─ 8.5 缓存写入
│     ResponseCache.set("query_logistics", {order_id: "ORD-001"}, response, ttl=30s)
│
├─ 9. 渠道适配
│     WechatAdapter.adapt_with_fallback()
│     → "logistics_timeline" 不在 wechat 支持列表 → downgrade 为纯文本
│     → ChannelMessage(channel="wechat", content_type="text")
│
└─ 10. 上下文保存
      ContextManager.save(context, response)
      → 更新 history, slots, token_usage, last_active_at
```

### 工具生命周期

每个工具的执行遵循严格的保证-补偿模式：

```
┌─────────┐    ┌───────────┐    ┌─────────┐    ┌──────────────┐    ┌──────────────┐
│ validate │───→│ pre_check │───→│ execute │───→│ format_result │───→│ LLM enhance  │
│ JSON模式 │    │ 业务前置   │    │ 核心逻辑 │    │ 人类可读格式   │    │ 自然语言润色  │
└─────────┘    └───────────┘    └─────────┘    └──────────────┘    └──────────────┘
     │              │                │
     │ 失败         │ 失败           │ 失败
     ▼              ▼                ▼
  ToolError     ToolError     compensate()
                                补偿回滚
```

### 多轮对话状态机

退款、投诉、订单查询等场景各维护独立 FSM，支持状态守卫和条件转换：

```
退款场景 (RefundScenarioFSM):
  initiated → confirmed → processing → completed
                        └→ cancelled

投诉场景 (ComplaintScenarioFSM):
  idle → received → classified → investigating → resolving → resolved
                                                    └→ escalated

订单查询 (OrderInquiryScenarioFSM):
  idle → querying → located → displaying → follow_up → completed
                                    └→ cancelled
```

### 数据飞轮

系统通过评测闭环和运营反馈持续自我改进。所有环节已接线到生产代码：

```
                    ┌─────────────────────────────┐
                    │         生产对话数据           │
                    │  StructuredFormatter (JSON)   │
                    │  AuditLogger + CostTracker    │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
     │  黄金数据集    │  │  LLM Judge   │  │  回归测试     │
     │ GoldenDataset │  │  自动质量评分  │  │ Regression   │
     │  500 标注样本  │  │  准确/安全    │  │  意图/实体    │
     │  覆盖 10 意图  │  │  有用/语气    │  │  工具/关键词  │
     └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
            │                 │                  │
            └────────┬────────┘                  │
                     ▼                           │
              ┌──────────────┐                   │
              │  质量报告      │◄──────────────────┘
              │  按意图/场景   │
              │  维度评分      │
              └──────┬───────┘
                     │
            ┌────────┴────────┐
            ▼                  ▼
     ┌──────────────┐  ┌──────────────┐
     │  优化意图规则  │  │  补充训练样本  │
     │  正则/权重调优 │  │ add_samples() │
     └──────┬───────┘  └──────┬───────┘
            │                  │
            └────────┬─────────┘
                     ▼
              ┌──────────────┐
              │  下一轮发布    │
              │  质量提升      │
              └──────────────┘
```

**飞轮各环节（均已接线到 main.py）：**

| 环节 | 组件 | 状态 | 作用 |
|------|------|------|------|
| 数据采集 | `StructuredFormatter` + `AuditLogger` / `DatabaseAuditLogger` | 运行中 | JSON 结构化日志，记录意图/实体/工具调用/Token消耗，DB 模式下持久化到 AuditRecord 表 |
| 成本追踪 | `CostTracker` / `DatabaseCostTracker` | 运行中 | 每次 LLM 调用后记录模型和 Token 用量，DB 模式下持久化到 CostRecord 表 |
| 链路追踪 | OpenTelemetry (10 span) | 运行中 | security/context/intent/tool 各环节独立 trace |
| Prometheus | 8 个指标 + Histogram 分桶 | 运行中 | /metrics 端点自动采集 |
| 黄金数据集 | `GoldenDataset` (500 样本) | 已加载 | 启动时注入 Level-2 语义匹配引擎 |
| 回归测试 | `python -m evaluation regression` | CLI 可用 | CI 中运行，≥80% 通过 exit 0 |
| LLM Judge | `python -m evaluation judge` | CLI 可用 | 4 维度评分（准确/安全/有用/语气），1-5 分 |
| 样本补充 | `IntentEngine.add_samples()` | 代码就绪 | 运营可调用接口动态补充样本 |
| 规则调优 | `RuleBasedMatcher.add_rule()` | 代码就绪 | 可动态调整正则权重 |

**评测 CLI：**

```bash
# 列出黄金数据集样本
python -m open_chat_shop.evaluation list

# 运行回归测试（CI 友好，≥80% 通过 exit 0）
python -m open_chat_shop.evaluation regression

# LLM Judge 质量评分
python -m open_chat_shop.evaluation judge
```

## 项目结构

```
open-chat-shop/
├── main.py                     # 入口：组装组件并启动 FastAPI
├── run.sh                      # 启动脚本（自动构建前端）
├── pyproject.toml              # 项目依赖（FastAPI, LiteLLM, SQLModel, Redis...）
├── Dockerfile                  # 多阶段构建，非 root 用户
├── docker-compose.yml          # api + postgres + redis + prometheus + grafana
├── .github/workflows/ci.yml    # GitHub Actions CI（lint/type/test/frontend/docker）
├── configs/                    # YAML 配置
│   ├── providers.yaml          # LLM Provider 配置
│   ├── tool_routing.yaml       # 工具路由规则
│   ├── security.yaml           # 安全策略
│   ├── scenarios.yaml          # 业务场景 FSM
│   └── channels.yaml           # 渠道配置
├── monitoring/                 # Prometheus + Grafana 配置
│   ├── prometheus/
│   │   └── alerts.yml          # 告警规则（错误率/延迟/LLM 故障）
│   └── grafana/
│       ├── datasources/        # Prometheus 数据源
│       └── dashboards/         # 预配置仪表盘
├── frontend/                   # 客户聊天前端（React + Ant Design）
│   ├── src/components/         #   ChatWindow, MessageBubble
│   ├── src/components/rich/    #   4 种富消息组件
│   └── dist/                   #   构建产物（.gitignore，./run.sh 自动构建）
├── frontend-agent/             # 坐席管理后台（独立 React 应用）
│   ├── src/pages/              #   LoginPage, DashboardPage
│   ├── src/components/         #   ConversationList, AgentChat, CustomerPanel
│   └── src/components/rich/    #   复用富消息组件
├── static/                     # 纯文本聊天 UI（Node.js 不可用时的后备）
├── src/open_chat_shop/
│   ├── core/                   # 核心引擎
│   │   ├── types.py            # 数据结构（Message, Intent, SessionContext...）
│   │   ├── exceptions.py       # 异常体系
│   │   ├── provider.py         # LLM Provider ABC
│   │   ├── litellm_provider.py # LiteLLM 实现（OpenAI/Anthropic/Ollama）
│   │   ├── context.py          # 上下文管理器
│   │   ├── intent.py           # 三级级联意图引擎
│   │   ├── tool.py             # 工具注册与动态注入
│   │   ├── strategy.py         # 对话策略
│   │   ├── orchestrator.py     # 对话编排器（主流程 + 缓存 + 链路追踪）
│   │   ├── security.py         # 安全防护层
│   │   ├── scenario.py         # 通用状态机 FSM
│   │   ├── slot_tracker.py     # 实体槽位追踪
│   │   ├── semantic_search.py  # 向量语义搜索
│   │   ├── cost_governance.py  # 成本治理
│   │   ├── rate_limiter.py     # 速率限制（内存 + Redis 双后端）
│   │   ├── middleware.py       # 编排器中间件
│   │   ├── handoff.py          # 人工转接队列（自动分配 + 回调通知）
│   │   ├── resilience.py       # 熔断器 + 重试策略
│   │   ├── cache.py            # 响应缓存（Redis + 内存双后端）
│   │   └── tool_response_mapper.py  # 工具结果 → 富消息映射
│   ├── tools/builtin/          # 8 个内置电商工具（构造器注入 Repository）
│   ├── channel/                # 多渠道适配 + Registry + 富消息渲染
│   ├── api/                    # REST + WebSocket + 流式响应 + 微信 Webhook
│   │   ├── app.py              #   主应用（含 Agent WebSocket + 安全头 + /metrics）
│   │   ├── agent.py            #   Agent REST API（7 个端点）
│   │   ├── streaming.py        #   SSE + WebSocket 流式响应
│   │   └── wechat.py           #   微信 Webhook
│   ├── storage/                # 会话持久化 + 数据模型 + Repository 层
│   │   ├── repositories/       # Repository ABC + InMemory + Database + Seed
│   │   ├── models.py           # SQLModel 数据模型（8 表）
│   │   ├── database.py         # 数据库初始化 + 会话管理
│   │   └── alembic/            # 数据库迁移
│   ├── evaluation/             # 评测框架（黄金数据集/回归/LLM-as-Judge）
│   └── observability/          # 日志/链路追踪 + Prometheus 指标 + DatabaseAuditLogger
├── tests/                      # 40+ 个测试文件（852 个测试用例）
│   ├── unit/                   #   单元测试
│   ├── integration/            #   集成测试
│   └── load/                   #   Locust 负载测试
└── docs/                       # 设计文档
```

## 内置测试数据

系统内置 mock 数据，启动即可体验全部功能，无需数据库。数据位于 `src/open_chat_shop/tools/builtin/_mock_data.py`。

**存储模式：**
- **内存模式**（默认）：`InMemory*Repository` 直接引用 mock dict，零配置即开即用
- **数据库模式**（设 `DATABASE_URL`）：`Database*Repository` 操作 SQLModel 表，`seed_if_empty()` 首次启动时自动从 mock 数据初始化

**订单（5 个）：**

| 订单号 | 状态 | 商品 | 金额 |
|--------|------|------|------|
| ORD-001 | 已发货 | 无线鼠标 + USB-C 扩展坞 | ¥228 |
| ORD-002 | 待处理 | 机械键盘 | ¥399 |
| ORD-003 | 处理中 | 显示器支架 x2 | ¥240 |
| ORD-004 | 已退款 | 高清摄像头 | ¥199 |
| ORD-005 | 已送达 | 笔记本电脑包 + 屏幕保护膜 | ¥109 |

**物流：** ORD-001（顺丰速运）、ORD-005（京东物流）有完整轨迹

**商品（12 件）：** 无线鼠标、USB-C 扩展坞、机械键盘、显示器支架、高清摄像头、笔记本电脑包、屏幕保护膜、LED 台灯、蓝牙音箱、人体工学椅、手机、耳机

**可体验的对话示例：**

```
你好
查询订单 ORD-001
ORD-001 物流到哪了
搜索手机
ORD-001 能退吗
退款 ORD-001
取消订单 ORD-002
修改地址 ORD-002
转人工客服
谢谢
```

## 内置工具

| 工具 | 功能 | 安全等级 |
|------|------|---------|
| `query_order` | 查询订单详情 | 只读 |
| `query_logistics` | 物流追踪 | 只读 |
| `search_product` | 商品搜索 | 只读 |
| `check_refund_eligibility` | 退款资格检查 | 只读 |
| `create_refund` | 创建退款申请 | 需确认 |
| `cancel_order` | 取消订单 | 需确认 |
| `modify_address` | 修改收货地址 | 需确认 |
| `handoff_to_human` | 转人工客服 | 自动 |

自定义工具只需继承 `BaseTool` 并实现 `execute` 方法：

```python
from open_chat_shop.core.tool import BaseTool, ToolResult

class MyCustomTool(BaseTool):
    name = "my_tool"
    description = "自定义工具示例"
    params_schema = {
        "type": "object",
        "required": ["param1"],
        "properties": {"param1": {"type": "string"}},
    }

    async def execute(self, params: dict, context) -> ToolResult:
        return ToolResult(success=True, data={"result": "done"})
```

## 技术栈

| 层次 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| Web 框架 | FastAPI + Uvicorn |
| LLM 集成 | LiteLLM（100+ 模型） |
| 数据模型 | SQLModel |
| 向量检索 | pgvector / 内存 |
| 会话存储 | Redis / 内存 / 数据库 |
| 可观测 | Prometheus + Grafana + OpenTelemetry + structlog |
| 弹性 | Circuit Breaker + Retry + Response Cache |
| 前端 | React 19 + Ant Design 6 + Vite 8 |
| CI/CD | GitHub Actions |
| 负载测试 | Locust |
| 容器化 | Docker（多阶段构建）+ Docker Compose |

## 生产部署检查清单

> 在将系统部署到生产环境之前，逐项确认以下事项。

### 必须

- [ ] **LLM API Key** — `OPENAI_API_KEY` 或 `ANTHROPIC_API_KEY` 已配置
- [ ] **JWT_SECRET_KEY** — 设为强随机字符串（`openssl rand -hex 32`），不能留空或使用默认值
- [ ] **TLS 终结** — 生产环境必须启用 HTTPS（nginx/traefik/cloud load balancer）
- [ ] **数据库密码** — PostgreSQL 使用强密码，不在 docker-compose 中使用 `commerce` 默认值
- [ ] **Redis 密码** — `REDIS_URL` 包含密码（`redis://:your-password@host:6379/0`）
- [ ] **CORS_ORIGINS** — 设为实际域名，不保留 `localhost` 默认值
- [ ] **DEV_MODE** — 确认未设置或设为 `false`
- [ ] **Grafana 密码** — 修改默认 admin 密码，关闭匿名访问

### 推荐

- [ ] **DATABASE_URL** — 指向托管 PostgreSQL 实例（非容器内实例）
- [ ] **数据库备份** — 配置 pg_dump 定时备份或云厂商快照
- [ ] **日志收集** — 接入 ELK/Loki 等远程日志系统
- [ ] **监控告警** — Prometheus 告警规则已配置并通知到运维通道
- [ ] **多 Worker** — 使用 gunicorn + uvicorn workers（见 docker-compose.prod.yml）
- [ ] **Alembic 迁移** — 启动前执行 `alembic upgrade head`

## License

[Apache 2.0](LICENSE)
