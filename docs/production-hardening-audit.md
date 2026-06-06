# 企业级生产化改造方案书

> 审计日期：2026-05-20
> 审计范围：全项目代码库（后端 + 前端 + Agent 前端 + 基础设施）
> 审计角色：高级架构师视角
> 严重级别：CRITICAL > HIGH > MEDIUM > LOW

---

## 执行摘要

| 级别 | 数量 | 说明 |
|------|------|------|
| CRITICAL | 3 | 必须修复，否则不可上线 |
| HIGH | 9 | 强烈建议修复，影响核心功能 |
| MEDIUM | 18 | 建议修复，影响运维效率与稳定性 |
| LOW | 2 | 锦上添花，可排期处理 |
| **合计** | **32** | |

**结论：当前系统不具备直接上线生产环境的条件。** 核心问题集中在三个方面：状态全部驻留在进程内存（重启即丢失）、安全机制不完整（密钥泄露风险）、缺乏跨 Worker 协调机制。建议按优先级分 3 个阶段改造，预计总工时 15-20 人天。

---

## 一、状态管理（4 项）

### C-01 [CRITICAL] HandoffQueue 全内存，重启丢失

**位置**: `src/open_chat_shop/core/handoff.py`

**问题**: `HandoffQueue` 的排队数据、坐席注册、会话分配全部保存在 Python dict/list 中。进程重启（部署、OOM Kill、崩溃）后所有排队中的客户请求和进行中的人工会话全部丢失。

**影响**: 生产环境中一次滚动部署就可能丢失几十个正在排队或正在服务中的会话。

**改造方案**:
1. 短期：引入 Redis 作为状态后端，`HandoffQueue` 的 `_queue`、`_agents`、`_active_transfers` 改用 Redis Hash + Sorted Set 存储
2. 中期：增加 `HandoffQueueRepository` 抽象层，支持 Redis / PostgreSQL 双后端切换
3. 关键接口：
   ```python
   class HandoffQueueRepository(Protocol):
       async def enqueue(self, request: TransferRequest) -> int: ...
       async def dequeue(self, request_id: str) -> TransferRequest | None: ...
       async def get_queue_position(self, request_id: str) -> int: ...
       async def register_agent(self, agent: HumanAgent) -> None: ...
       async def deregister_agent(self, agent_id: str) -> None: ...
       async def get_available_agents(self, department: str) -> list[HumanAgent]: ...
   ```

**工时**: 3 天

---

### S-02 [HIGH] `_session_modes` / `_session_messages` 无持久化

**位置**: `src/open_chat_shop/api/app.py:154-157`

**问题**: 会话模式（AI_MODE / HUMAN_MODE / TRANSFER_PENDING）和会话消息历史存储在 `create_app()` 的闭包变量中。多 Worker 部署时各 Worker 状态不同步，导致：
- Worker A 接受了转接请求，Worker B 不知道该会话已进入 HUMAN_MODE
- 客户消息路由到错误的 Worker，AI 仍然响应本应由人工处理的消息

**改造方案**:
1. 会话模式：存入 Redis（`session:{id}:mode`），每次请求前读取
2. 消息历史：写入 Redis Stream 或数据库，按 `session_id` 分区
3. SessionContext 的 `mode` 字段改为从 Redis 读取而非内存 dict

**工时**: 2 天

---

### S-03 [HIGH] WebSocket 连接映射无共享

**位置**: `src/open_chat_shop/api/app.py:154-155`（`_agent_sockets`, `_customer_sockets`）

**问题**: WebSocket 连接对象（`_agent_sockets`, `_customer_sockets`）天然不能跨进程共享。多 Worker 场景下：
- Agent 连在 Worker A，客户连在 Worker B → 消息无法转发
- 广播通知只发送到当前 Worker 上的连接

**改造方案**:
1. 引入 Redis Pub/Sub 作为跨 Worker 消息总线
2. 每个 Worker 启动时订阅 `channel:agent:{agent_id}` 和 `channel:customer:{session_id}`
3. 发送消息时：先查本地 WebSocket dict → 有则直接发 → 无则 Publish 到 Redis → 其他 Worker 收到后转发
4. 架构图：
   ```
   Worker A                    Redis                    Worker B
   Agent WS ←── Subscribe ──── Pub/Sub ──── Publish ──── Customer WS
   ```

**工时**: 3 天

---

### S-04 [MEDIUM] 会话消息无分页、无过期清理

**位置**: `src/open_chat_shop/api/app.py:156`

**问题**: `_session_messages` 只往里 append，没有清理机制。长时间运行后内存持续增长。

**改造方案**:
1. 消息持久化到 Redis Stream（自动分页，支持 XRANGE）
2. 或持久化到数据库，加 TTL 过期清理
3. 设置单会话消息上限（如 1000 条），超限自动截断旧消息

**工时**: 1 天

---

## 二、并发安全（3 项）

### CC-01 [HIGH] HandoffQueue.assign() 无并发锁

**位置**: `src/open_chat_shop/core/handoff.py` — `assign()` 方法

**问题**: 多个坐席同时接受同一个排队请求时，没有分布式锁保护。可能导致：
- 同一个请求被分配给两个坐席
- 客户同时收到两条"已接入"消息

**改造方案**:
1. 使用 Redis `SETNX` 实现分布式锁：`LOCK:assign:{request_id}`
2. 或使用 Redis 事务（MULTI/EXEC）保证原子性
3. `assign()` 方法增加乐观锁检查

**工时**: 1 天

---

### CC-02 [HIGH] `_on_assign_cb` 使用 `get_event_loop().create_task()`

**位置**: `src/open_chat_shop/api/app.py:507-515`

**问题**: `_on_assign_cb` 和 `_on_complete_cb` 使用 `_aio.get_event_loop().create_task()` 在回调中调度异步任务。这是不安全的：
- 在非异步上下文中调用 `get_event_loop()` 可能在 Python 3.12+ 中行为变化
- 没有异常捕获，`create_task()` 创建的任务如果抛异常会静默丢失

**改造方案**:
1. 改用 `asyncio.ensure_future()` + 顶层异常处理器
2. 或使用 `BackgroundTask` 模式统一管理异步回调
3. 所有 `create_task` 调用必须包裹 `try/except`

**工时**: 0.5 天

---

### CC-03 [MEDIUM] Orchestrator.handle_message() 无请求超时

**位置**: `src/open_chat_shop/core/orchestrator.py`

**问题**: 单次对话处理没有整体超时控制。如果 LLM API 卡住或工具执行超时，请求会无限挂起，占用连接资源。

**改造方案**:
1. 在 `handle_message()` 外层包裹 `asyncio.wait_for(handle_message(), timeout=30)`
2. 超时后返回降级响应："抱歉，处理超时，请稍后重试"
3. 不同意图类型可设置不同超时（查询类 10s，退款确认 30s）

**工时**: 0.5 天

---

## 三、数据持久化（5 项）

### DP-01 [CRITICAL] 会话上下文依赖内存 SessionManager

**位置**: `src/open_chat_shop/core/session.py`

**问题**: `SessionManager` 的所有上下文数据（用户意图、对话历史、订单引用）存储在内存 dict 中。进程重启 = 所有会话从零开始，用户需要重新描述需求。

**改造方案**:
1. 引入 `SessionRepository` 抽象：
   ```python
   class SessionRepository(Protocol):
       async def get(self, session_id: str) -> SessionContext | None: ...
       async def save(self, ctx: SessionContext) -> None: ...
       async def delete(self, session_id: str) -> None: ...
   ```
2. 实现 Redis 版本（短期）和 PostgreSQL 版本（中期）
3. SessionContext 改用 Pydantic model 方便序列化/反序列化

**工时**: 2 天

---

### DP-02 [MEDIUM] 商品/订单数据为硬编码 mock

**位置**: `src/open_chat_shop/tools/builtin/_mock_data.py`

**问题**: 所有商品、订单、物流数据都是硬编码的 Python dict。无法接入真实电商后端。

**改造方案**:
1. 定义 `ProductRepository` / `OrderRepository` / `LogisticsRepository` 协议接口
2. MockRepository 实现现有数据（保留开发测试能力）
3. 新增 HttpRepository 实现，对接真实电商 API
4. 通过配置文件切换 Repository 实现

**工时**: 2 天

---

### DP-03 [MEDIUM] 无数据库迁移机制

**问题**: 项目没有 Alembic 或其他数据库迁移工具。当前虽然不直接用数据库，但持久化改造后需要。

**改造方案**:
1. 引入 SQLAlchemy + Alembic
2. 初始化核心表结构：`sessions`、`messages`、`transfer_requests`、`agents`
3. 迁移脚本纳入 CI/CD 流程

**工时**: 1 天

---

### DP-04 [MEDIUM] 无审计日志

**问题**: 关键操作（退款、转人工、坐席分配、会话完成）没有持久化的审计记录。无法回溯问题、统计报表、合规审查。

**改造方案**:
1. 定义审计事件类型：`SESSION_CREATED`、`TRANSFER_REQUESTED`、`AGENT_ASSIGNED`、`REFUND_INITIATED` 等
2. 审计日志写入独立数据表（或发送到专门的审计服务）
3. 保留 90 天，支持按 session_id / 时间范围查询

**工时**: 1 天

---

### DP-05 [MEDIUM] 降级逻辑过于简单

**位置**: `src/open_chat_shop/core/session.py` — `InMemorySessionManager`

**问题**: 当 Redis 连接失败时，静默降级到内存模式，没有告警。运维人员无法感知状态后端已降级。

**改造方案**:
1. 降级时记录 WARN 日志 + 触发 Prometheus metric
2. 健康检查端点区分 `degraded` 状态（返回 200 但标记降级）
3. 持续降级超过 N 分钟后触发告警

**工时**: 0.5 天

---

## 四、错误处理（4 项）

### EH-01 [HIGH] AnthropicProvider 每次调用创建新 client

**位置**: `src/open_chat_shop/providers/anthropic.py`

**问题**: 每次 `generate()` 调用都重新创建 `anthropic.Anthropic()` client 实例，导致：
- 无法复用 HTTP 连接池
- 连接建立开销叠加在每次请求上
- 请求级别的错误没有重试机制

**改造方案**:
1. Client 实例在 Provider 初始化时创建，作为单例复用
2. 添加指数退避重试（3 次，间隔 1s/2s/4s）
3. 添加请求超时控制（默认 30s）
4. 区分可重试错误（429, 500, 502, 503）和不可重试错误（400, 401）

**工时**: 1 天

---

### EH-02 [MEDIUM] 工具执行无异常隔离

**位置**: `src/open_chat_shop/tools/` 各工具

**问题**: 单个工具执行抛异常时，整个对话流程中断。缺乏工具级别的 try-catch 隔离。

**改造方案**:
1. 在 `ToolRegistry.execute()` 外层包裹统一异常处理
2. 工具异常返回 `ToolError` 结果而非抛异常
3. Orchestrator 收到 `ToolError` 后生成友好的降级回复

**工时**: 0.5 天

---

### EH-03 [MEDIUM] XML 解析无安全防护

**位置**: `src/open_chat_shop/core/orchestrator.py` — XML 工具调用解析

**问题**: 使用 `xml.etree.ElementTree` 解析 LLM 生成的 XML，没有防护：
- billion laughs 攻击（XML 炸弹）
- 拒绝服务（超大 XML）

**改造方案**:
1. 限制 XML 输入长度（如最大 10KB）
2. 禁用 XML 外部实体（`defusedxml` 库）
3. 或改用正则表达式解析简单的工具调用格式

**工时**: 0.5 天

---

### EH-04 [MEDIUM] 静默吞异常

**位置**: 多处 `except Exception: pass`

**问题**: `app.py` 中多处 `except Exception: pass`，特别是 `_notify_agents` 和客户通知回调。异常被静默吞掉，无法排查问题。

**改造方案**:
1. 所有 `except` 至少记录 `logger.warning` 或 `logger.error`
2. 区分可忽略异常（如 WebSocket 已关闭）和需要关注的异常
3. 关键路径上的异常触发 metric

**工时**: 0.5 天

---

## 五、安全（6 项）

### SE-01 [CRITICAL] .env 中 API Key 已提交到仓库

**位置**: 项目根目录 `.env` 文件

**问题**: `.env` 文件中包含真实的 `ANTHROPIC_API_KEY`，且可能已提交到 git 历史中。这是最严重的安全隐患。

**改造方案**:
1. **立即**: 将 `.env` 加入 `.gitignore`（如果还没有）
2. **立即**: 使用 `git filter-branch` 或 `BFG Repo Cleaner` 从 git 历史中删除敏感信息
3. **立即**: 轮换已泄露的 API Key
4. 添加 pre-commit hook 防止再次提交 `.env` 文件
5. 提供 `.env.example` 模板文件

**工时**: 0.5 天（紧急）

---

### SE-02 [HIGH] Agent WebSocket 无认证

**位置**: `src/open_chat_shop/api/app.py:569-641`

**问题**: Agent WebSocket 端点 (`/ws/agent/{agent_id}`) 无任何认证。任何人只要知道 URL 就能：
- 注册为坐席
- 看到所有排队请求
- 接入客户会话
- 读取客户消息

**改造方案**:
1. WebSocket 连接时验证 JWT token（通过 query param 或 first message）
2. 坐席必须先通过 REST API `/api/v1/agent/login` 获取 token
3. WebSocket 连接建立后先验证 token，失败则关闭连接
4. 增加坐席权限等级（只看 / 可接入 / 可管理）

**工时**: 1.5 天

---

### SE-03 [MEDIUM] API Key 比较未使用 timing-safe

**位置**: `src/open_chat_shop/api/auth.py`

**问题**: API Key 验证可能使用普通字符串比较（`==`），存在时序攻击风险。

**改造方案**:
1. 使用 `hmac.compare_digest()` 进行密钥比较
2. 检查所有密钥/Token 比较代码，统一使用 timing-safe 方法

**工时**: 0.5 天

---

### SE-04 [MEDIUM] CORS 配置过于宽松

**位置**: `src/open_chat_shop/api/app.py:122-134`

**问题**: 开发环境 CORS 允许 localhost，但生产环境有警告逻辑而非阻止。`allow_methods=["*"]` 和 `allow_headers=["*"]` 过于宽松。

**改造方案**:
1. 生产环境必须显式配置 `CORS_ORIGINS`，否则拒绝启动
2. 限制 `allow_methods` 为实际使用的方法：`GET, POST, PUT, OPTIONS`
3. 限制 `allow_headers` 为实际需要的头：`Authorization, Content-Type`

**工时**: 0.5 天

---

### SE-05 [MEDIUM] 无速率限制

**问题**: 所有 API 端点和 WebSocket 无速率限制。恶意用户可以：
- 高频发送消息消耗 LLM API 配额
- 暴力注册坐席
- DDoS WebSocket 连接

**改造方案**:
1. 引入 `slowapi` 或自研限流中间件
2. REST API: 60 次/分钟/IP
3. WebSocket: 30 条消息/分钟/session
4. 坐席注册: 5 次/分钟/IP

**工时**: 1 天

---

### SE-06 [MEDIUM] 输入清洗不足

**问题**: 用户输入直接传递给 LLM 和工具，没有清洗。虽然 LLM 注入风险主要靠 Prompt Engineering 缓解，但仍需基础防护。

**改造方案**:
1. 输入长度限制（最大 2000 字符）
2. 过滤控制字符
3. WebSocket 消息大小限制

**工时**: 0.5 天

---

## 六、可扩展性（4 项）

### SC-01 [HIGH] 无跨 Worker 会话锁定

**问题**: 多 Worker 部署时，同一会话的并发请求可能被不同 Worker 同时处理，导致：
- 并发冲突（上下文状态不一致）
- LLM 重复调用（浪费成本）

**改造方案**:
1. 引入 Redis 分布式锁：`LOCK:session:{session_id}`
2. 请求处理前获取锁，处理后释放
3. 锁超时 30s 防止死锁
4. 获取锁失败时返回"请稍后重试"

**工时**: 1 天

---

### SC-02 [MEDIUM] 无水平扩展方案

**问题**: 当前架构假设单进程运行。多 Worker / 多实例部署时 WebSocket 状态不共享。

**改造方案**:
1. 部署架构：Nginx 负载均衡 + 多 Uvicorn Worker + Redis
2. WebSocket 使用 sticky session（基于 session_id）
3. 跨 Worker 消息通过 Redis Pub/Sub 传递（见 S-03）
4. 健康检查端点支持 Kubernetes 探针

**工时**: 2 天

---

### SC-03 [MEDIUM] 无优雅关闭

**问题**: 进程被 SIGTERM 时，进行中的 WebSocket 连接和请求直接中断。

**改造方案**:
1. 实现 FastAPI lifespan shutdown hook
2. 关闭流程：停止接受新连接 → 等待进行中请求完成（最多 10s）→ 关闭 WebSocket 连接 → 退出
3. 通知所有已连接的坐席和客户端"服务即将重启"

**工时**: 0.5 天

---

### SC-04 [MEDIUM] Agent 前端构建未集成

**问题**: `frontend-agent/` 是独立 Vite 项目，需要单独启动。生产部署需要统一构建流程。

**改造方案**:
1. 构建脚本将 `frontend-agent/` 的产物输出到 `static/agent/`
2. 后端 `app.py` 同时挂载客户前端和 Agent 前端的静态文件
3. 或使用 Nginx 分别代理两个前端 + 后端 API

**工时**: 0.5 天

---

## 七、可观测性（4 项）

### OB-01 [MEDIUM] Prometheus 指标未接入实际数据

**位置**: `src/open_chat_shop/observability/metrics.py`

**问题**: Metrics 端点存在但可能未真正记录数据。关键业务指标缺失：
- 对话处理延迟（P50/P95/P99）
- 意图识别准确率
- 工具调用成功率/失败率
- 人工转接等待时间
- 坐席利用率

**改造方案**:
1. 在 Orchestrator 关键路径添加 Histogram 指标
2. 在 HandoffQueue 添加 Gauge 指标（排队数、活跃坐席数）
3. 在 Provider 层添加 Counter 指标（调用次数、Token 消耗）
4. Grafana 仪表盘模板

**工时**: 1.5 天

---

### OB-02 [MEDIUM] 结构化日志不完整

**问题**: 日志格式不统一，缺少关键上下文（session_id, user_id, request_id）。

**改造方案**:
1. 统一使用 JSON 结构化日志
2. 每条日志自动注入：timestamp, level, request_id, session_id, duration_ms
3. 使用 `structlog` 或 Python `logging` + JSON formatter
4. 日志级别规范：ERROR（需要人工介入）> WARNING（降级/重试成功）> INFO（关键业务事件）> DEBUG

**工时**: 1 天

---

### OB-03 [MEDIUM] 无分布式追踪

**问题**: 单次对话请求涉及多个内部组件（Orchestrator → Strategy → Tool → Provider），缺乏端到端追踪。

**改造方案**:
1. 引入 OpenTelemetry
2. 关键 span：`orchestrator.handle_message`、`strategy.analyze`、`tool.execute`、`provider.generate`
3. 请求入口注入 trace_id，贯穿所有组件
4. 接入 Jaeger 或 Zipkin 查看

**工时**: 1.5 天

---

### OB-04 [MEDIUM] 无告警规则

**问题**: 没有定义任何告警规则。系统异常时无法及时通知运维。

**改造方案**:
1. 定义告警规则：
   - API 错误率 > 5% → P1
   - WebSocket 断连率 > 10% → P2
   - LLM 调用延迟 P95 > 10s → P2
   - 排队等待 > 5 分钟 → P3
   - 坐席利用率 > 90% → P3
2. 接入钉钉/企业微信/Slack 通知
3. 告警收敛：相同告警 5 分钟内不重复

**工时**: 1 天

---

## 八、可靠性（3 项）

### RL-01 [HIGH] 成本追踪未接入真实数据

**问题**: Token 使用和成本追踪依赖 Provider 返回的数据，如果 Provider 响应格式变化或数据缺失，成本数据不准。

**改造方案**:
1. 在 Provider 层统一记录 input_tokens / output_tokens
2. 成本计算使用配置化的价格表（按模型）
3. 每日成本报表 + 预算超限告警

**工时**: 1 天

---

### RL-02 [MEDIUM] 熔断器配置硬编码

**位置**: Provider 层熔断逻辑

**问题**: 熔断器参数（失败阈值、恢复时间）硬编码在代码中，无法根据生产情况调整。

**改造方案**:
1. 熔断器参数改为环境变量或配置文件
2. 支持运行时动态调整（通过管理 API）
3. 熔断状态变化时发送告警

**工时**: 0.5 天

---

### RL-03 [MEDIUM] 无数据备份策略

**问题**: 持久化改造后需要配套的备份方案，目前为零。

**改造方案**:
1. Redis: 开启 AOF 持久化 + 定期 RDB 快照
2. PostgreSQL: 每日全量备份 + WAL 增量备份
3. 备份保留 30 天，定期验证恢复流程

**工时**: 0.5 天

---

## 九、配置管理（2 项）

### CF-01 [MEDIUM] 硬编码的模型名称和参数

**位置**: Provider 配置、Strategy 参数

**问题**: 模型名称（如 `claude-sonnet-4-20250514`）、温度参数、最大 Token 数等硬编码在代码中。模型更新时需要改代码重新部署。

**改造方案**:
1. 所有模型参数提取到 `config.yaml` 或环境变量
2. 支持按意图类型配置不同模型和参数
3. 模型切换无需重启（热加载配置）

**工时**: 0.5 天

---

### CF-02 [LOW] 环境变量无验证

**问题**: 启动时没有验证必需的环境变量是否存在。`ANTHROPIC_API_KEY` 缺失时到第一次请求才报错。

**改造方案**:
1. 使用 Pydantic Settings 在启动时验证所有必需配置
2. 缺少必需配置时拒绝启动并打印清晰的错误信息
3. 配置变更时触发 WARN 日志

**工时**: 0.5 天

---

## 十、测试覆盖（4 项）

### T-01 [HIGH] Agent API 无单元测试

**问题**: `src/open_chat_shop/api/agent.py` 的 REST 端点没有单元测试覆盖。

**改造方案**:
1. 为每个端点编写正常流程 + 边界条件测试
2. 使用 `httpx.AsyncClient` + FastAPI TestClient
3. Mock HandoffQueue 依赖

**工时**: 1 天

---

### T-02 [MEDIUM] WebSocket 交互测试缺失

**问题**: 客户-坐席双向消息流没有自动化测试。

**改造方案**:
1. 使用 `websockets` 库编写异步测试
2. 覆盖：连接建立、消息收发、断线重连、会话模式切换
3. 集成到 CI 流程

**工时**: 1 天

---

### T-03 [MEDIUM] 负载测试为零

**问题**: 不知道系统在并发场景下的表现。

**改造方案**:
1. 使用 Locust 或 k6 编写负载测试
2. 基准场景：100 并发 WebSocket 连接，每秒 10 条消息
3. 确定系统瓶颈和最大承载能力

**工时**: 1 天

---

### T-04 [MEDIUM] 前端组件无单元测试

**问题**: React 组件（MessageBubble、ChatWindow、OrderCard 等）没有单元测试。

**改造方案**:
1. 使用 Vitest + React Testing Library
2. 覆盖：富消息渲染、会话模式切换、WebSocket 重连
3. 目标覆盖率 80%

**工时**: 1.5 天

---

## 十一、部署架构（补充）

当前部署方式为单进程 `python3 main.py`，不具备生产条件。

### 目标架构

```
                    ┌─────────────┐
                    │   Nginx     │
                    │  (LB + WS)  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐┌────┴─────┐┌────┴─────┐
        │ Uvicorn   ││ Uvicorn  ││ Uvicorn  │
        │ Worker 1  ││ Worker 2 ││ Worker 3 │
        └─────┬─────┘└────┬─────┘└────┬─────┘
              │            │            │
              └────────────┼────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐┌────┴─────┐┌────┴─────┐
        │  Redis    ││PostgreSQL││ Anthropic│
        │ (State +  ││(Persist) ││   API    │
        │  PubSub)  ││          ││          │
        └───────────┘└──────────┘└──────────┘
```

### 关键组件

| 组件 | 用途 | 替代方案 |
|------|------|----------|
| Redis | 会话状态 + Pub/Sub + 分布式锁 + 消息队列 | Valkey, Dragonfly |
| PostgreSQL | 持久化存储（消息、审计、坐席） | MySQL, TiDB |
| Nginx | 负载均衡 + WebSocket 代理 + 静态文件 | Caddy, Traefik |
| Prometheus + Grafana | 监控 + 告警 | Datadog, New Relic |

---

## 实施路线图

### Phase 1: 安全 + 稳定性（5 天）— 上线前必须完成

| 优先级 | 项目 | 工时 |
|--------|------|------|
| C | SE-01: API Key 泄露修复 | 0.5d |
| C | DP-01: 会话上下文持久化 | 2d |
| C | S-01: HandoffQueue Redis 后端 | 3d |
| H | S-02: 会话模式 Redis 存储 | 2d |
| H | SE-02: Agent WebSocket 认证 | 1.5d |
| H | EH-01: Provider Client 复用 + 重试 | 1d |

> Phase 1 总工时约 10 天，但部分可并行，实际耗时约 5 天。

### Phase 2: 可扩展性 + 可观测性（4 天）

| 优先级 | 项目 | 工时 |
|--------|------|------|
| H | S-03: WebSocket 跨 Worker (Redis Pub/Sub) | 3d |
| H | CC-01: 分配并发锁 | 1d |
| H | SC-01: 会话分布式锁 | 1d |
| M | OB-01: Prometheus 真实指标 | 1.5d |
| M | OB-02: 结构化日志 | 1d |

### Phase 3: 生产化完善（5 天）

| 优先级 | 项目 | 工时 |
|--------|------|------|
| M | DP-02: 商品/订单 Repository 抽象 | 2d |
| M | DP-03: 数据库迁移 | 1d |
| M | OB-03: 分布式追踪 | 1.5d |
| M | T-01 ~ T-04: 测试覆盖 | 4.5d |
| M | 其余 MEDIUM 项 | 3d |

---

## 总结

| 阶段 | 工时 | 核心目标 |
|------|------|----------|
| Phase 1 | ~5d | 消除安全风险 + 实现状态持久化 |
| Phase 2 | ~4d | 支持多 Worker 部署 + 可观测性 |
| Phase 3 | ~5d | 业务抽象 + 测试覆盖 + 运维完善 |
| **合计** | **~14d** | **约 3 周** |

完成 Phase 1 后可进行内部灰度测试。完成 Phase 2 后可上线小规模生产。完成 Phase 3 后达到企业级标准。

---

*本方案书由架构审计自动生成，需结合团队资源和业务优先级调整实施顺序。*
