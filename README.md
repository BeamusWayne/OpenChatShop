<div align="center">

# OpenChatShop

**模型无关的开源电商智能对话系统**

一套代码适配 OpenAI / Anthropic / Qwen / DeepSeek / Ollama 等任意 LLM 后端，
快速搭建生产级电商客服 Agent。

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-898%20passing-brightgreen)]()

[快速开始](#快速开始) · [系统架构](#系统架构) · [设计决策](#设计决策) · [技术栈](#技术栈) · [部署](#生产部署)

</div>

---

## 目录

- [核心特性](#核心特性)
- [快速开始](#快速开始)
- [系统架构](#系统架构)
  - [分层架构](#分层架构)
  - [请求处理流水线](#请求处理流水线)
  - [意图识别三级级联](#意图识别三级级联)
  - [工具生命周期](#工具生命周期)
  - [人工转接状态机](#人工转接状态机)
  - [弹性容错](#弹性容错)
  - [数据飞轮](#数据飞轮)
- [前端架构](#前端架构)
- [设计决策](#设计决策)
- [多渠道接入](#多渠道接入)
- [监控与可观测性](#监控与可观测性)
- [内置工具](#内置工具)
- [内置测试数据](#内置测试数据)
- [项目结构](#项目结构)
- [技术栈](#技术栈)
- [生产部署](#生产部署)
- [License](#license)

---

## 核心特性

| 能力 | 说明 |
|------|------|
| **模型无关** | Provider 抽象层解耦 LLM 依赖，YAML 配置切换模型，无需改代码 |
| **三级意图级联** | 规则匹配 → 语义检索 → LLM 分类，按置信度逐级升级，平衡速度和准确率 |
| **可插拔工具系统** | 8 个内置电商工具 + 自定义工具继承 `BaseTool`，4 层过滤动态注入 |
| **富消息渲染** | 订单卡片、物流时间线、商品网格、转接状态 4 种富消息组件 |
| **人工客服后台** | 独立坐席管理界面，三栏布局，WebSocket 实时通知，自动分配 |
| **四层安全防护** | Prompt 注入检测 → 内容安全过滤 → RBAC 权限校验 → 输出脱敏 |
| **业务状态机** | 售前咨询 / 售后处理 / 退款流程独立 FSM，可编排组合 |
| **多渠道适配** | Web + 微信公众号 + 微信小程序统一接口，11 种富消息类型自动降级 |
| **Repository 层** | 5 个 Repository ABC，零配置内存模式 + `DATABASE_URL` 自动切换数据库 |
| **弹性容错** | 熔断器 + 指数退避重试 + 响应缓存，保护 LLM 调用 |
| **可观测性** | Prometheus + Grafana + OpenTelemetry + 结构化审计日志 |
| **生产就绪** | JWT/API Key 认证、速率限制、成本治理、Docker 多阶段构建、gunicorn workers |

---

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+（可选，用于富消息前端和坐席后台）

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
./run.sh
```

无需任何配置即可体验完整对话功能。系统内置规则引擎处理订单查询、商品搜索、物流追踪、退款、转人工等场景。

> 安装了 Node.js 时，`./run.sh` 自动构建 React 前端（首次较慢），提供富消息卡片渲染。
> 未安装 Node.js 时，使用内置纯文本聊天界面，功能不受影响。

服务启动后访问：

| 地址 | 说明 |
|------|------|
| http://localhost:8000/ | 聊天界面 |
| http://localhost:8000/docs | API 文档（Swagger） |
| http://localhost:8000/health | 存活探针 |
| http://localhost:8000/health/ready | 就绪探针（检查 DB + Redis） |
| http://localhost:8000/metrics | Prometheus 指标 |

### 启动人工客服后台

```bash
# 先启动后端
./run.sh

# 新终端，启动坐席后台
cd frontend-agent && npm install && npm run dev
```

访问 http://localhost:5174/ ，输入坐席名称即可进入三栏管理界面。

坐席后台功能：
- 排队列表实时更新（WebSocket 推送）
- 一键接入客户会话
- 双向实时聊天
- 客户信息面板
- 后端重启后自动重连并注册

### 配置 LLM Provider（可选）

默认使用规则引擎，无需 LLM。接入大模型提升智能度：

```bash
cp .env.example .env
# 编辑 .env，填入 API Key
```

### 配置数据库（可选）

默认使用内存模式，无需数据库。需要持久化时：

```bash
# .env 中添加：
DATABASE_URL=sqlite:///data/shop.db                    # SQLite
# DATABASE_URL=postgresql://user:pass@host:5432/shop   # PostgreSQL（生产推荐）
```

首次启动自动建表并从 mock 数据集初始化，重启后数据不丢失。

### Docker Compose

```bash
docker compose up    # api + postgres + redis + prometheus + grafana
```

| 服务 | 端口 | 说明 |
|------|------|------|
| agent-api | 8000 | 主 API 服务 |
| postgres | 5432 (内部) | pgvector 数据库 |
| redis | 6379 (内部) | 缓存 + 限速 + 会话 |
| prometheus | 9090 | 指标采集 |
| grafana | 3000 | 监控仪表盘 |

---

## 系统架构

### 分层架构

系统采用严格的分层设计，每一层只依赖下一层，不跨层调用：

```mermaid
graph TB
    subgraph "渠道层 Channel"
        W["WebAdapter"]
        WX["WechatAdapter"]
        MP["MiniProgramAdapter"]
        CR["ChannelRegistry<br/>自动路由 · 降级兜底"]
    end

    subgraph "API 层 FastAPI"
        REST["REST API"]
        SSE["SSE 流式"]
        WS["WebSocket"]
        WH["微信 Webhook"]
        AA["Agent REST + WS"]
        SEC["SecurityHeaders"]
        MET["/metrics"]
    end

    subgraph "对话编排层 Orchestrator"
        direction LR
        SG["SecurityGuard"] --> CM["ContextManager"]
        CM --> IE["IntentEngine"]
        IE --> TI["ToolInjector"]
        TI --> ST["Strategy"]
        ST --> EX["Execute"]
    end

    subgraph "弹性层 Resilience"
        CB["CircuitBreaker"]
        RT["RetryPolicy"]
        RC["ResponseCache"]
        RL["RateLimiter"]
        BG["BudgetManager"]
    end

    subgraph "Repository 抽象层"
        OR["OrderRepo"]
        PR["ProductRepo"]
        LR2["LogisticsRepo"]
        RR["RefundRepo"]
        HR["HandoffRepo"]
        IM["InMemory（默认）"]
        DB["Database（DATABASE_URL）"]
    end

    subgraph "LLM Provider 抽象层"
        P1["Anthropic"]
        P2["OpenAI"]
        P3["Qwen / DeepSeek"]
        P4["Ollama"]
        CS["CascadeStrategy"]
    end

    subgraph "基础设施层"
        REDIS["Redis<br/>限速 · 缓存 · 会话"]
        PG["PostgreSQL<br/>pgvector · 持久化"]
        OTEL["OpenTelemetry<br/>链路追踪"]
        PROM["Prometheus<br/>+ Grafana"]
        LOG["审计日志<br/>成本追踪"]
    end

    CR --> REST
    W --> CR
    WX --> CR
    MP --> CR
    REST --> SG
    SG --> CB
    CB --> OR
    OR --> P1
    P1 --> REDIS
    OR --> PG
    CB --> OTEL
```

### 请求处理流水线

一条用户消息从接收到回复经过 10 个阶段，每个阶段有独立的错误处理和可观测性：

```mermaid
sequenceDiagram
    participant U as 用户
    participant API as API 层
    participant SEC as 安全防护
    participant CTX as 上下文
    participant INT as 意图引擎
    participant CACHE as 响应缓存
    participant TOOL as 工具系统
    participant STR as 策略引擎
    participant LLM as LLM Provider
    participant CH as 渠道适配

    U->>API: POST /api/v1/chat
    API->>SEC: check_input()
    Note over SEC: 注入检测 → PII 脱敏 → RBAC

    SEC->>CTX: load(session_id)
    Note over CTX: 加载历史 · Token 预算分配

    CTX->>INT: classify(content)
    Note over INT: 规则(≥0.85) → 语义(≥0.70) → LLM(≥0.50)

    INT->>CACHE: 查询缓存
    alt 缓存命中
        CACHE-->>CH: 直接返回缓存结果
    else 缓存未命中
        CACHE->>STR: decide(intent, tools)
        STR->>TOOL: execute()
        TOOL->>LLM: enhance(result)
        Note over LLM: CircuitBreaker + Retry 保护
        LLM-->>CACHE: 写入缓存
        CACHE->>CH: adapt(channel)
    end
    CH-->>U: AgentMessage
```

**详细阶段说明：**

| 阶段 | 组件 | 职责 | 失败策略 |
|------|------|------|---------|
| 1. API 接入 | `ChannelRegistry` | 按渠道选择适配器，构建 `UserMessage` | 400 参数错误 |
| 2. 安全检查 | `SecurityGuard` | 注入检测 → PII 脱敏 → RBAC 权限 | 403 拦截 + 审计日志 |
| 3. 上下文加载 | `ContextManager` | 加载历史、分配 Token 预算（20/50/20/10） | 创建新会话 |
| 4. 意图识别 | `CascadeIntentEngine` | 三级级联识别 + 实体提取 | fallback 兜底意图 |
| 5. 缓存查询 | `ResponseCache` | 读操作结果缓存 | 未命中继续 |
| 6. 工具注入 | `ToolInjector` | 意图→场景→权限→数量 4 层过滤 | 空工具集 |
| 7. 策略决策 | `RuleBasedStrategy` | 参数完整性检查 → 确认 → 执行 | 追问缺失参数 |
| 8. 工具执行 | `BaseTool` | validate → pre_check → execute → compensate | 补偿回滚 |
| 9. 响应构建 | `ToolResponseMapper` | 工具结果 → 富消息 + LLM 润色 | 纯文本兜底 |
| 10. 渠道适配 | `ChannelAdapter` | 按渠道能力降级不支持的类型 | 文本 fallback |

### 意图识别三级级联

```mermaid
graph TD
    INPUT["用户输入"] --> L1

    subgraph "Level 1: 规则匹配"
        L1["RuleBasedMatcher<br/>正则加权匹配"]
    end

    L1 -->|置信度 ≥ 0.85| OK["返回意图"]
    L1 -->|置信度 < 0.85| L2

    subgraph "Level 2: 语义检索"
        L2["SemanticSearch<br/>向量相似度 / Jaccard"]
    end

    L2 -->|置信度 ≥ 0.70| OK
    L2 -->|置信度 < 0.70| L3

    subgraph "Level 3: LLM 分类"
        L3["LiteLLM Provider<br/>大模型意图判断"]
    end

    L3 -->|置信度 ≥ 0.50| OK
    L3 -->|置信度 < 0.50| FB["Fallback<br/>未识别意图"]

    style L1 fill:#4CAF50,color:white
    style L2 fill:#FF9800,color:white
    style L3 fill:#F44336,color:white
    style OK fill:#2196F3,color:white
    style FB fill:#9E9E9E,color:white
```

**设计理由：**
- **Level 1**（毫秒级）：正则匹配覆盖高频场景（查订单、查物流），零成本
- **Level 2**（<100ms）：语义检索覆盖模糊表达（"快递到哪了" → 物流查询），低成本
- **Level 3**（秒级）：LLM 分类兜底复杂表达，高成本但高准确率
- 级联策略保证 90%+ 请求在 Level 1-2 完成，大幅降低 LLM 调用成本

### 工具生命周期

每个工具遵循严格的保证-补偿（Saga）模式：

```mermaid
stateDiagram-v2
    [*] --> Validate: 调用工具
    Validate --> PreCheck: JSON Schema 校验通过
    Validate --> [*]: 校验失败 → ToolError

    PreCheck --> Execute: 业务前置检查通过
    PreCheck --> [*]: 前置检查失败 → ToolError

    Execute --> FormatResult: 核心逻辑执行成功
    Execute --> Compensate: 执行失败

    FormatResult --> Enhance: 格式化结果
    Enhance --> [*]: LLM 润色（可选）

    Compensate --> [*]: 补偿回滚

    note right of Validate: 参数类型/必填校验
    note right of PreCheck: 订单存在性/退款资格等
    note right of Execute: 通过 Repository 访问数据
    note right of Compensate: 撤销已执行的副作用
```

### 人工转接状态机

系统通过 `SessionMode` 管理 AI 与人工客服的切换：

```mermaid
stateDiagram-v2
    [*] --> AI_MODE: 用户连接
    AI_MODE --> TRANSFER_PENDING: 用户请求转人工<br/>或 AI 判断需转接
    TRANSFER_PENDING --> HUMAN_MODE: 坐席接入
    TRANSFER_PENDING --> AI_MODE: 排队超时<br/>自动升级回 AI
    HUMAN_MODE --> AI_MODE: 坐席结束服务
    HUMAN_MODE --> AI_MODE: 坐席断线超时

    note right of AI_MODE: 智能助手处理所有消息<br/>显示快捷操作卡片
    note right of TRANSFER_PENDING: AI 静默<br/>显示排队位置 + 预计等待
    note right of HUMAN_MODE: AI 完全静默<br/>消息直接转发坐席<br/>UI 切换为人工客服模式
```

**端到端流程：**

```mermaid
sequenceDiagram
    participant C as 客户
    participant Q as HandoffQueue
    participant API as Agent API
    participant A as 坐席

    C->>Q: "转人工" → 排队
    Q->>API: WebSocket 推送 new_request
    API->>A: 坐席看到排队列表

    alt 有空闲坐席
        A->>API: POST /accept/{session_id}
        API->>Q: try_auto_assign()
        Q->>C: WebSocket 推送 "坐席已接入"
        Q->>A: WebSocket 推送 session_history
        loop 实时对话
            C->>A: customer_message
            A->>C: agent_message
        end
        A->>API: POST /complete/{session_id}
        API->>C: "人工服务已结束，回到 AI 模式"
    else 无空闲坐席
        Q->>C: 显示 "排队第 N 位，预计等待 M 分钟"
        Q->>Q: 超时后自动升级
    end
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

Agent WebSocket：`ws://localhost:8000/ws/agent/{agent_id}`

| 方向 | 事件 | 说明 |
|------|------|------|
| 服务端→坐席 | `queue_state` | 连接后发送当前队列 |
| 服务端→坐席 | `new_request` | 新客户排队 |
| 服务端→坐席 | `request_assigned` | 会话已分配 |
| 服务端→坐席 | `session_history` | AI 对话历史 |
| 服务端→坐席 | `customer_message` | 客户消息 |
| 坐席→服务端 | `agent_message` | 坐席回复 |
| 坐席→服务端 | `heartbeat` | 心跳保活 |

### 弹性容错

```mermaid
graph TD
    subgraph "熔断器 Circuit Breaker"
        CLOSED["CLOSED<br/>正常调用"] -->|"连续 5 次失败"| OPEN["OPEN<br/>熔断中"]
        OPEN -->|"30 秒后"| HALF["HALF_OPEN<br/>探针模式"]
        HALF -->|"探针成功"| CLOSED
        HALF -->|"探针失败"| OPEN
    end

    subgraph "重试策略"
        R1["第 1 次重试<br/>等待 1s"]
        R2["第 2 次重试<br/>等待 2s"]
        R3["第 3 次重试<br/>等待 4s"]
        R1 --> R2 --> R3
    end

    subgraph "响应缓存"
        CA["search_product: TTL 5min"]
        CB["query_order: TTL 1min"]
        CC["query_logistics: TTL 30s"]
    end
```

| 机制 | 参数 | 保护对象 |
|------|------|---------|
| 熔断器 | failure_threshold=5, recovery_timeout=30s | LLM Provider 调用 |
| 重试 | max_retries=3, 指数退避 1s→2s→4s | TimeoutError / ConnectionError |
| 缓存 | Redis / 内存双后端 | 读操作（商品/订单/物流） |
| 限速 | 滑动窗口，Redis Lua 原子脚本 | 用户 30/min, IP 60/min, 工具 1000/h |
| 预算 | SessionBudgetManager | 单会话 Token 消耗上限 |

### 数据飞轮

```mermaid
graph LR
    subgraph "数据采集"
        A1["结构化日志<br/>StructuredFormatter"]
        A2["审计日志<br/>AuditLogger"]
        A3["成本追踪<br/>CostTracker"]
    end

    subgraph "评测引擎"
        B1["黄金数据集<br/>500 标注样本"]
        B2["回归测试<br/>RegressionRunner"]
        B3["LLM Judge<br/>4 维度评分"]
    end

    subgraph "优化闭环"
        C1["意图规则调优"]
        C2["样本补充"]
        C3["下一轮发布"]
    end

    A1 --> B1
    A2 --> B2
    A3 --> B3

    B1 --> C1
    B2 --> C2
    B3 --> C1

    C1 --> C3
    C2 --> C3
    C3 -.->|生产数据| A1
```

**飞轮各环节（均已接线到 main.py）：**

| 环节 | 组件 | 状态 |
|------|------|------|
| 数据采集 | `StructuredFormatter` + `DatabaseAuditLogger` | 运行中 |
| 成本追踪 | `DatabaseCostTracker` → CostRecord 表 | 运行中 |
| 链路追踪 | OpenTelemetry（10 个 span） | 运行中 |
| 指标采集 | Prometheus 8 个指标 + Histogram 分桶 | 运行中 |
| 黄金数据集 | `GoldenDataset`（500 样本，覆盖 10 意图） | 已加载 |
| 回归测试 | `python -m open_chat_shop.evaluation regression` | CLI 可用 |
| LLM Judge | 4 维度评分（准确/安全/有用/语气） | CLI 可用 |

```bash
# 评测 CLI
python -m open_chat_shop.evaluation list         # 列出黄金数据集
python -m open_chat_shop.evaluation regression   # CI 回归（≥80% 通过 exit 0）
python -m open_chat_shop.evaluation judge        # LLM Judge 质量评分
```

---

## 前端架构

系统包含两个独立 React 应用 + 一个静态 HTML 兜底：

```
frontend/                     客户聊天界面（React 19 + Ant Design 6）
├── src/hooks/
│   └── useChat.ts           聊天 hook + sessionMode 状态机
├── src/components/
│   ├── ChatWindow.tsx        聊天主窗口（按 mode 切换 UI）
│   ├── WelcomeScreen.tsx     欢迎界面 + 快捷操作卡片
│   ├── MessageBubble.tsx     消息气泡（AI/客服/系统/用户 4 种样式）
│   └── rich/                 富消息组件
│       ├── OrderCard.tsx     订单卡片
│       ├── LogisticsTimeline.tsx  物流时间线
│       ├── ProductGrid.tsx   商品网格
│       └── TransferStatus.tsx  转接状态

frontend-agent/               坐席管理后台（独立 React 应用）
├── src/hooks/
│   └── useAgent.ts           Agent WebSocket + REST API hook
├── src/pages/
│   ├── LoginPage.tsx         坐席注册
│   └── DashboardPage.tsx     三栏管理界面
├── src/components/
│   ├── ConversationList.tsx  排队 / 进行中 / 已结束
│   ├── AgentChat.tsx         坐席聊天窗口
│   ├── CustomerPanel.tsx     客户信息面板
│   └── QuickReplies.tsx      快捷回复

static/                       纯文本聊天 UI（Node.js 不可用时的后备）
└── index.html                单文件，WebSocket 连接，无需构建
```

**富消息渲染逻辑：**

```mermaid
graph TD
    MSG["AgentMessage"] --> CHECK{messageType?}

    CHECK -->|order_card| OC["OrderCard<br/>订单号 · 商品 · 金额 · 状态标签"]
    CHECK -->|logistics_timeline| LT["LogisticsTimeline<br/>物流商 · 运单号 · 轨迹时间线"]
    CHECK -->|product_list| PG["ProductGrid<br/>商品卡片网格（图/名/价）"]
    CHECK -->|transfer| TS["TransferStatus<br/>排队位置 · 预计等待 · 坐席接入"]
    CHECK -->|text / 其他| TXT["纯文本气泡"]

    OC --> RENDER["MessageBubble 渲染"]
    LT --> RENDER
    PG --> RENDER
    TS --> RENDER
    TXT --> RENDER
```

**示例对话：**

```
用户: "查询订单 ORD-001"
AI:  [订单卡片] ORD-001 | 无线鼠标+扩展坞 | ¥228 | 已发货

用户: "物流查询"
AI:  [物流时间线] 顺丰速运 SF1234567890
      ● 已发货 (05-15 14:30)
      ● 运输中 (05-16 08:00)
      ○ 派送中

用户: "搜索手机"
AI:  [商品网格] 手机 ¥4999 | 蓝牙音箱 ¥199 | ...

用户: "转人工"
AI:  [转接状态] 正在为您转接... 排队第 2 位，预计等待 3 分钟
```

---

## 设计决策

以下记录了系统中的关键架构决策及其理由。

### 1. Repository 模式解耦存储层

**决策：** 所有工具通过构造器注入 Repository 接口访问数据，不直接操作数据源。

**理由：**
- 工具（`query_order` 等）只依赖 `OrderRepository` ABC，不知道底层是内存 dict 还是 PostgreSQL
- 测试时注入 `InMemoryRepository`，生产时注入 `DatabaseRepository`，工具代码零修改
- `__init__(repo=None)` 默认创建 InMemory，898 个现有测试零修改通过

```mermaid
graph LR
    T["工具层<br/>query_order<br/>search_product<br/>..."] --> R["Repository ABC<br/>find_by_id()<br/>search()<br/>..."]

    R --> M["InMemoryRepo<br/>默认 · 零配置"]
    R --> D["DatabaseRepo<br/>DATABASE_URL 触发"]

    D --> DB["PostgreSQL<br/>pgvector"]
    M --> MOCK["_mock_data.py"]
```

### 2. 三级意图级联而非纯 LLM

**决策：** 意图识别采用规则 → 语义 → LLM 三级级联，而非直接调 LLM。

**理由：**
- 纯 LLM 每次调用成本 $0.01-0.05，高频场景日均万次调用，月成本数千美元
- 规则引擎覆盖 60%+ 高频意图，响应时间 <5ms，成本为零
- 语义检索覆盖 25%+ 模糊表达，响应时间 <100ms，成本极低
- LLM 仅兜底 15% 复杂表达，大幅降低总成本

### 3. Channel Adapter 模式而非渠道硬编码

**决策：** 每个渠道实现 `ChannelAdapter` ABC，通过 `ChannelRegistry` 自动路由。

**理由：**
- 微信公众号只支持 3 种消息类型，小程序支持 6 种，Web 全量 11 种
- Adapter 的 `downgrade()` 方法将不支持的类型自动降级为纯文本
- 新增渠道（抖音、飞书、钉钉）只需实现 Adapter + 注册，不改核心代码

### 4. 工具 Saga 补偿模式

**决策：** 工具执行采用 validate → pre_check → execute → compensate 流程。

**理由：**
- 退款、取消订单等操作有副作用，失败时需要回滚已执行的步骤
- `compensate()` 方法在每个工具中实现，保证最终一致性
- 例如 `create_refund` 失败时，`compensate()` 恢复订单状态为原值

### 5. 会话存储双模式

**决策：** 默认 InMemory，设 `DATABASE_URL` 自动切换数据库，设 `REDIS_URL` 启用 Redis 会话。

**理由：**
- 开发者 clone 后零配置即可运行，降低上手门槛
- 生产环境通过环境变量切换，代码不需要改
- `seed_if_empty()` 首次启动自动从 mock 数据初始化数据库

### 6. Provider 级联降级

**决策：** LLM Provider 支持配置多个后端，按优先级级联降级。

**理由：**
- 主 Provider（如 Anthropic）故障时，自动切换到备选（OpenAI），再降到本地（Ollama）
- 通过 `CascadeStrategy` 统一管理，业务层无感知
- `providers.yaml` 配置驱动，运行时无需重启即可切换

---

## 多渠道接入

```mermaid
graph TD
    REQ["请求 channel 字段"] --> CR["ChannelRegistry"]

    CR -->|"web"| WA["WebAdapter<br/>11 种消息类型"]
    CR -->|"wechat"| WCA["WechatAdapter<br/>3 种 + 自动降级"]
    CR -->|"miniprogram"| MPA["MiniProgramAdapter<br/>6 种 + 自动降级"]
    CR -->|"未知"| WA

    WA --> RESP["响应"]
    WCA -->|"支持"| RESP
    WCA -->|"不支持"| DOWNGRADE["downgrade() → 纯文本"]
    MPA -->|"支持"| RESP
    MPA -->|"不支持"| DOWNGRADE
    DOWNGRADE --> RESP
```

### 消息类型支持矩阵

| 消息类型 | Web | 微信公众号 | 微信小程序 |
|---------|-----|----------|----------|
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

### 接入微信公众号

1. `.env` 中配置 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` / `WECHAT_TOKEN`
2. 微信公众平台 → 开发 → 服务器地址：`https://your-domain/api/v1/wechat/callback`
3. 微信验签通过后即可接收消息并自动回复

### 接入微信小程序

1. `.env` 中配置小程序变量
2. 小程序前端发送消息时设置 `channel: "miniprogram"`：

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

```python
from open_chat_shop.channel.base import ChannelAdapter
from open_chat_shop.channel.registry import default_registry

class MyChannelAdapter(ChannelAdapter):
    # 实现 adapt(), get_capabilities(), downgrade()
    ...

registry = default_registry()
registry.register("my_channel", MyChannelAdapter())
```

---

## 监控与可观测性

### Prometheus 指标

`/metrics` 端点暴露：

| 指标 | 类型 | 说明 |
|------|------|------|
| `openchatshop_chat_requests_total` | Counter | 聊天请求（按 intent/status 分维） |
| `openchatshop_chat_duration_seconds` | Histogram | 请求延迟（分桶 0.1s-10s） |
| `openchatshop_llm_calls_total` | Counter | LLM 调用（按 model/status） |
| `openchatshop_llm_tokens_total` | Counter | Token 消耗（按 model/type） |
| `openchatshop_tool_calls_total` | Counter | 工具调用（按 tool/status） |
| `openchatshop_cache_hits_total` | Counter | 缓存命中（按 intent） |
| `openchatshop_active_sessions` | Gauge | 活跃会话数 |
| `openchatshop_handoff_queue_size` | Gauge | 人工转接排队数 |

### 告警规则

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

所有 HTTP 响应自动添加：

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy: default-src 'self'`
- HTTPS 时自动添加 `Strict-Transport-Security`

---

## 内置工具

| 工具 | 功能 | 安全等级 | 需确认 |
|------|------|---------|-------|
| `query_order` | 查询订单详情 | 只读 | 否 |
| `query_logistics` | 物流追踪 | 只读 | 否 |
| `search_product` | 商品搜索 | 只读 | 否 |
| `check_refund_eligibility` | 退款资格检查 | 只读 | 否 |
| `create_refund` | 创建退款申请 | 写入 | 是 |
| `cancel_order` | 取消订单 | 写入 | 是 |
| `modify_address` | 修改收货地址 | 写入 | 是 |
| `handoff_to_human` | 转人工客服 | 自动 | 否 |

自定义工具只需继承 `BaseTool`：

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

---

## 内置测试数据

系统内置 mock 数据，启动即可体验全部功能。数据位于 `src/open_chat_shop/tools/builtin/_mock_data.py`。

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

---

## 项目结构

```
open-chat-shop/
├── main.py                     # 入口：组装组件 + 启动 FastAPI
├── run.sh                      # 一键启动（自动构建前端）
├── pyproject.toml              # 依赖（FastAPI, LiteLLM, SQLModel, Redis）
├── Dockerfile                  # 3 阶段构建（frontend + python + runtime）
├── docker-compose.yml          # 开发：api + postgres + redis + prometheus + grafana
├── docker-compose.prod.yml     # 生产：强制密码，关闭匿名，内存限制
├── gunicorn.conf.py            # 多 worker 配置（CPU*2+1）
├── .github/workflows/ci.yml    # CI: lint → type-check → test → frontend → docker
│
├── configs/                    # YAML 配置
│   ├── providers.yaml          #   LLM Provider 配置
│   ├── tool_routing.yaml       #   工具路由规则
│   ├── security.yaml           #   安全策略
│   ├── scenarios.yaml          #   业务场景 FSM
│   └── channels.yaml           #   渠道配置
│
├── monitoring/                 # 可观测性
│   ├── prometheus/
│   │   └── alerts.yml          #   告警规则（错误率/延迟/LLM 故障）
│   └── grafana/
│       ├── datasources/        #   Prometheus 数据源
│       └── dashboards/         #   预配置仪表盘
│
├── deploy/                     # 生产部署
│   ├── nginx.conf              #   TLS 终结 + WebSocket 代理 + 限流
│   └── docker-compose.nginx.yml  # Compose 覆盖（添加 nginx）
│
├── frontend/                   # 客户聊天前端（React 19 + Ant Design 6 + Vite）
│   ├── src/hooks/useChat.ts    #   聊天 hook + sessionMode 状态机
│   ├── src/components/
│   │   ├── ChatWindow.tsx      #   聊天主窗口
│   │   ├── WelcomeScreen.tsx   #   欢迎界面 + 快捷操作
│   │   ├── MessageBubble.tsx   #   消息气泡（4 种样式）
│   │   └── rich/               #   4 种富消息组件
│   └── dist/                   #   构建产物（./run.sh 自动构建）
│
├── frontend-agent/             # 坐席管理后台（独立 React 应用）
│   ├── src/hooks/useAgent.ts   #   Agent WebSocket + REST API hook
│   ├── src/pages/              #   LoginPage, DashboardPage
│   └── src/components/         #   ConversationList, AgentChat, CustomerPanel
│
├── static/                     # 纯文本聊天 UI（无 Node.js 时的后备）
│
├── src/open_chat_shop/
│   ├── core/                   # 核心引擎
│   │   ├── types.py            #   数据结构（Message, Intent, SessionContext...）
│   │   ├── exceptions.py       #   异常体系（6 个子异常 + 错误码前缀）
│   │   ├── provider.py         #   LLM Provider ABC（chat/stream/embed）
│   │   ├── litellm_provider.py #   LiteLLM 实现（100+ 模型）
│   │   ├── anthropic_provider.py  # Anthropic 原生 Provider
│   │   ├── context.py          #   上下文管理器（InMemory / Redis / DB）
│   │   ├── intent.py           #   三级级联意图引擎
│   │   ├── tool.py             #   工具注册 + 动态注入（4 层过滤）
│   │   ├── strategy.py         #   对话策略引擎
│   │   ├── orchestrator.py     #   对话编排器（主流程）
│   │   ├── security.py         #   安全防护层（4 层防护）
│   │   ├── scenario.py         #   通用状态机 FSM 框架
│   │   ├── slot_tracker.py     #   多轮实体槽位追踪
│   │   ├── semantic_search.py  #   向量语义搜索
│   │   ├── cost_governance.py  #   成本治理（会话预算 + 告警）
│   │   ├── rate_limiter.py     #   速率限制（滑动窗口，Redis/内存）
│   │   ├── middleware.py       #   编排器中间件管道
│   │   ├── handoff.py          #   人工转接队列（自动分配 + 回调）
│   │   ├── resilience.py       #   熔断器 + 重试策略
│   │   ├── cache.py            #   响应缓存（Redis/内存双后端）
│   │   ├── config.py           #   Pydantic 配置校验
│   │   └── tool_response_mapper.py  # 工具结果 → 富消息映射
│   │
│   ├── tools/builtin/          # 8 个内置电商工具
│   │   ├── query_order.py      #   查询订单
│   │   ├── query_logistics.py  #   物流追踪
│   │   ├── search_product.py   #   商品搜索
│   │   ├── check_refund_eligibility.py  # 退款资格检查
│   │   ├── create_refund.py    #   创建退款
│   │   ├── cancel_order.py     #   取消订单
│   │   ├── modify_address.py   #   修改地址
│   │   ├── handoff_to_human.py #   转人工客服
│   │   └── _mock_data.py       #   内置测试数据（5 订单 / 12 商品）
│   │
│   ├── channel/                # 多渠道适配
│   │   ├── base.py             #   ChannelAdapter ABC
│   │   ├── web.py              #   WebAdapter（11 种消息类型）
│   │   ├── miniprogram.py      #   MiniProgramAdapter（6 种 + 降级）
│   │   ├── renderers.py        #   11 种消息类型渲染器
│   │   └── registry.py         #   ChannelRegistry 自动路由
│   │
│   ├── api/                    # API 层
│   │   ├── app.py              #   主应用（路由 + Agent WS + 安全头）
│   │   ├── auth.py             #   JWT + API Key 认证
│   │   ├── agent.py            #   Agent REST API（7 个端点）
│   │   ├── streaming.py        #   SSE + WebSocket 流式响应
│   │   └── wechat.py           #   微信 Webhook
│   │
│   ├── storage/                # 存储层
│   │   ├── repositories/       #   Repository ABC + InMemory + Database + Seed
│   │   │   ├── abc.py          #     5 个 ABC（Order/Product/Logistics/Refund/Handoff）
│   │   │   ├── memory.py       #     InMemory 实现（包装 _mock_data）
│   │   │   ├── database.py     #     Database 实现（SQLModel）
│   │   │   └── seeding.py      #     seed_if_empty() 自动初始化
│   │   ├── models.py           #   SQLModel 数据模型（8 表）
│   │   ├── database.py         #   数据库初始化 + 会话管理
│   │   ├── redis_context.py    #   Redis 上下文管理器
│   │   ├── db_context.py       #   数据库会话持久化
│   │   └── alembic/            #   数据库迁移
│   │
│   ├── evaluation/             # 评测框架
│   │   ├── golden_dataset.py   #   黄金数据集（500 标注样本）
│   │   ├── regression.py       #   回归测试运行器
│   │   └── llm_judge.py        #   LLM 评分器（4 维度）
│   │
│   └── observability/          # 可观测性
│       ├── logging.py          #   结构化日志 + DB 审计 + 成本追踪
│       ├── metrics.py          #   Prometheus 指标（8 个）
│       └── tracing.py          #   OpenTelemetry（10 span）
│
├── tests/                      # 测试（898 个用例）
│   ├── unit/                   #   单元测试
│   ├── integration/            #   集成测试
│   ├── e2e/                    #   端到端测试
│   └── load/                   #   Locust 负载测试
│
└── docs/                       # 设计文档 + 迭代记录
```

---

## 技术栈

| 层次 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| Web 框架 | FastAPI + Uvicorn + gunicorn |
| LLM 集成 | LiteLLM（100+ 模型统一接口） |
| 数据模型 | SQLModel（Pydantic + SQLAlchemy） |
| 向量检索 | pgvector / 内存 |
| 会话存储 | Redis / 内存 / PostgreSQL |
| 可观测 | Prometheus + Grafana + OpenTelemetry |
| 弹性 | Circuit Breaker + Retry + Response Cache |
| 前端（客户） | React 19 + Ant Design 6 + Vite |
| 前端（坐席） | React 19 + Ant Design 6 + Vite |
| 容器化 | Docker（3 阶段构建）+ Docker Compose |
| CI/CD | GitHub Actions（5 Job 并行） |
| 负载测试 | Locust |
| 数据库迁移 | Alembic |

---

## 生产部署

### 检查清单

#### 必须

- [ ] **LLM API Key** — `OPENAI_API_KEY` 或 `ANTHROPIC_API_KEY` 已配置
- [ ] **JWT_SECRET_KEY** — `openssl rand -hex 32` 生成强随机字符串
- [ ] **TLS 终结** — nginx / Caddy / Traefik + Let's Encrypt
- [ ] **数据库密码** — PostgreSQL 强密码，不使用默认值
- [ ] **Redis 密码** — `REDIS_URL` 包含密码
- [ ] **CORS_ORIGINS** — 设为实际域名
- [ ] **DEV_MODE** — 确认未设置或 `false`
- [ ] **Grafana** — 修改默认密码，关闭匿名访问

#### 推荐

- [ ] **DATABASE_URL** — 指向托管 PostgreSQL
- [ ] **数据库备份** — pg_dump 定时备份 + 异地存档
- [ ] **日志收集** — ELK / Loki
- [ ] **监控告警** — Prometheus 告警 → 运维通道
- [ ] **多 Worker** — gunicorn + uvicorn workers（见 docker-compose.prod.yml）

### 环境变量

| 变量 | 说明 | 必填 |
|------|------|------|
| `ANTHROPIC_API_KEY` | Anthropic / 智谱 GLM API Key | 接入 LLM 时 |
| `ANTHROPIC_BASE_URL` | 自定义 API 端点 | 否 |
| `GLM_MODEL` | 模型名称（默认 glm-5.1） | 否 |
| `OPENAI_API_KEY` | OpenAI API Key | 否 |
| `DATABASE_URL` | 数据库连接串 | 持久化时 |
| `REDIS_URL` | Redis 连接串 | 否 |
| `JWT_SECRET_KEY` | JWT 签名密钥 | 生产必须 |
| `API_KEY` | 静态 API Key（与 JWT 二选一） | 否 |
| `AGENT_SECRET` | 坐席注册密钥 | 生产建议 |
| `CORS_ORIGINS` | 跨域来源（逗号分隔） | 生产必须 |
| `LOG_LEVEL` | 日志级别（默认 INFO） | 否 |
| `DEV_MODE` | 开发模式（跳过认证检查） | 仅开发 |
| `DEPLOY_ENV` | 部署环境（dev / production） | 否 |

### TLS / HTTPS

```bash
# 1. 准备 SSL 证书
mkdir -p deploy/ssl
cp your-cert.pem deploy/ssl/cert.pem
cp your-key.pem  deploy/ssl/key.pem

# 2. 编辑 deploy/nginx.conf，修改 server_name

# 3. 使用 nginx 覆盖启动
docker compose -f docker-compose.prod.yml -f deploy/docker-compose.nginx.yml up -d
```

**Let's Encrypt 自动证书：**

```bash
certbot certonly --standalone -d shop.example.com --email admin@example.com
# cert: /etc/letsencrypt/live/shop.example.com/fullchain.pem
# key:  /etc/letsencrypt/live/shop.example.com/privkey.pem
```

### Docker 生产部署

```bash
# 使用生产 compose（强制密码、关闭匿名、内存限制）
cp .env.production.example .env
# 编辑 .env，填入所有必填值
docker compose -f docker-compose.prod.yml up -d
```

---

## License

[Apache 2.0](LICENSE)
