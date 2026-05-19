# 接口契约（Contracts）

> 本文档是所有跨模块接口的**唯一定义源**。模块文档引用本文档而非重复定义。
>
> 变更规则：修改本文档中的任何接口必须全局 review 受影响模块。

---

## 0. 全局约定

### 0.1 命名格式

- **意图标识**：英文 snake_case（如 `query_order`、`request_refund`），配置文件中的 `display_name` 用中文展示名。所有模块统一使用英文标识符做路由和匹配。
- **工具名称**：英文 snake_case（如 `query_order`、`cancel_order`）。
- **消息类型**：英文 snake_case（见 §12 消息类型清单）。

### 0.2 异步模型

- 所有 I/O 操作使用 `async/await`。
- 同一会话的并发消息处理：编排器对同一 `session_id` 加异步锁（`asyncio.Lock`），保证串行处理。
- 无锁场景（不同会话间）可完全并行。

---

## 1. 核心数据结构

### 1.1 Message

```python
@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
```

### 1.2 Attachment

```python
@dataclass
class Attachment:
    type: Literal["image", "file", "audio", "video"]
    url: str
    name: str | None = None
    size_bytes: int | None = None
    mime_type: str | None = None
```

### 1.3 UserMessage

```python
@dataclass
class UserMessage:
    session_id: str
    content: str
    channel: str                    # "web" | "wechat" | "miniprogram" | "app" | "api"
    user_id: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
```

### 1.4 AgentMessage

```python
@dataclass
class AgentMessage:
    message_type: str               # 见 §12 消息类型清单
    payload: dict                   # 类型相关的结构化数据
    text_fallback: str              # 纯文本降级（所有渠道可用）
    suggestions: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
```

### 1.5 Intent

```python
@dataclass
class Intent:
    name: str                       # 英文标识（如 "query_order"）
    display_name: str               # 展示名（如 "查询订单"）
    confidence: float               # 0.0 - 1.0
    source: str                     # "rule" | "semantic" | "llm"
    entities: dict = field(default_factory=dict)
```

### 1.6 SessionContext

```python
@dataclass
class SessionContext:
    session_id: str
    user_id: str | None
    channel: str
    history: list[Message]
    summary: str | None
    slots: dict                     # 实体槽位（见 §1.7）
    fsm_state: str
    current_scenario: str | None
    token_usage: int
    user_role: str = "customer"
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active_at: datetime = field(default_factory=datetime.utcnow)
```

### 1.7 Slot Tracker 格式

```json
{
  "order_id": "ORD-20260519-001",
  "product_sku": "SKU-888",
  "complaint_type": "quality",
  "refund_amount": null,
  "user_sentiment": "neutral",
  "intent_confidence": 0.72
}
```

### 1.8 ToolResult

```python
@dataclass
class ToolResult:
    success: bool
    data: dict | None = None
    error: str | None = None
    sensitive_fields: list[str] = field(default_factory=list)
    latency_ms: int = 0
```

---

## 2. 异常体系

### 2.1 基础异常

```python
class OpenChatShopError(Exception):
    """所有模块异常的基类"""
    error_code: str                 # 模块前缀 + 编号，如 "PROV-001"
    message: str
    details: dict
    recoverable: bool               # 是否可自动恢复

    def __init__(self, error_code: str, message: str,
                 details: dict | None = None, recoverable: bool = True):
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        self.recoverable = recoverable
        super().__init__(message)
```

### 2.2 模块异常

```python
class SecurityError(OpenChatShopError):
    """安全层异常 — 默认不可恢复"""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(f"SEC-{hash(message) % 1000:03d}", message, details, recoverable=False)

class ProviderError(OpenChatShopError):
    """LLM Provider 异常"""
    def __init__(self, message: str, provider: str, details: dict | None = None):
        super().__init__(f"PROV-{hash(message) % 1000:03d}", message, details)
        self.provider = provider

class ContextError(OpenChatShopError):
    """上下文管理异常"""
    def __init__(self, message: str, session_id: str, details: dict | None = None):
        super().__init__(f"CTX-{hash(message) % 1000:03d}", message, details)
        self.session_id = session_id

class IntentError(OpenChatShopError):
    """意图识别异常"""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(f"INTENT-{hash(message) % 1000:03d}", message, details)

class ToolError(OpenChatShopError):
    """工具执行异常"""
    def __init__(self, message: str, tool_name: str, details: dict | None = None):
        super().__init__(f"TOOL-{hash(message) % 1000:03d}", message, details)
        self.tool_name = tool_name

class ChannelError(OpenChatShopError):
    """渠道适配异常"""
    def __init__(self, message: str, channel: str, details: dict | None = None):
        super().__init__(f"CHAN-{hash(message) % 1000:03d}", message, details)
        self.channel = channel
```

### 2.3 错误传播规则

| 异常类型 | 编排器处理 | 用户感知 |
|----------|-----------|---------|
| `SecurityError` | 中断请求，记录审计日志 | "您的消息包含不当内容，请修改后重试" |
| `ProviderError` (recoverable) | 降级到下一级 Provider | 无感知（透明降级） |
| `ProviderError` (!recoverable) | 返回错误消息 | "系统繁忙，请稍后重试" |
| `ContextError` | 返回错误消息 | "会话已过期，请重新开始" |
| `IntentError` | 回退到兜底意图 `fallback` | 返回通用回复 + 快捷入口 |
| `ToolError` | 返回执行失败信息 | "操作暂时无法完成，请稍后重试" |
| `ChannelError` | 降级到 `text_fallback` | 收到纯文本消息 |

---

## 3. LLM Provider 接口

> 实现细节见 [provider-layer.md](./provider-layer.md)

### 3.1 LLMProvider ABC

```python
class LLMProvider(ABC):
    """所有 LLM 提供者必须实现的接口。
    底层由 LiteLLM 统一适配，本层负责级联策略和降级逻辑。
    """

    @abstractmethod
    async def chat(self, messages: list[Message],
                   tools: list[ToolDefinition] | None = None,
                   config: GenerateConfig) -> LLMResponse:
        """同步对话接口。tools 为空时不启用 function calling。
        Raises: ProviderError 调用失败时
        """

    @abstractmethod
    async def stream(self, messages: list[Message],
                     tools: list[ToolDefinition] | None = None,
                     config: GenerateConfig) -> AsyncIterator[LLMChunk]:
        """流式对话接口。
        Raises: ProviderError 调用失败时
        """

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """文本向量化接口。
        Raises: ProviderError 调用失败时
        """

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """声明该 Provider 支持的能力。"""

    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """估算 Token 消耗（用于预算管理）。"""
```

### 3.2 ToolDefinition（LLM 视角的工具描述）

```python
@dataclass
class ToolDefinition:
    """传给 LLM 的工具描述 — 与 BaseTool 分离，LLM 不感知实现细节"""
    name: str
    description: str
    parameters: dict                # JSON Schema
```

### 3.3 Provider 辅助类型

```python
@dataclass
class ProviderCapabilities:
    tool_calling: bool
    streaming: bool
    vision: bool
    max_context_tokens: int
    supported_locales: list[str]

@dataclass
class GenerateConfig:
    temperature: float = 0.3
    max_tokens: int = 4096
    stop_sequences: list[str] = field(default_factory=list)
    timeout_seconds: int = 30
    retries: int = 2                # 单次调用最大重试次数
    retry_delay_seconds: float = 1.0

@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage
    finish_reason: str              # "stop" | "tool_calls" | "length" | "error"

@dataclass
class LLMChunk:
    content_delta: str
    tool_call_delta: ToolCall | None = None
    finish_reason: str | None = None

@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
```

---

## 4. Tool 接口

> 实现细节见 [tool-system.md](./tool-system.md)

### 4.1 BaseTool ABC

```python
class BaseTool(ABC):
    """内置工具基类"""
    name: str                       # 英文 snake_case
    description: str
    category: str
    params_schema: dict             # JSON Schema
    permissions: ToolPermission

    @abstractmethod
    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        """执行工具逻辑。
        Raises: ToolError 执行失败时
        """

    def validate(self, params: dict) -> ValidationResult:
        """参数校验（基于 JSON Schema）。"""

    async def pre_check(self, params: dict, context: SessionContext) -> CheckResult:
        """业务前置校验（库存检查、权限验证等）。默认通过。"""
        return CheckResult(passed=True)

    async def compensate(self, params: dict, context: SessionContext) -> None:
        """补偿逻辑（写操作失败时回滚）。默认无操作。"""

    def to_definition(self) -> ToolDefinition:
        """转换为 LLM 可见的工具描述。"""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.params_schema,
        )
```

### 4.2 Tool 辅助类型

```python
@dataclass
class ToolPermission:
    required_roles: list[str]
    sensitive_output: bool = False
    idempotent: bool = True
    requires_confirmation: bool = False
    confirmation_threshold: dict | None = None  # {"field": "amount", "gt": 500}

@dataclass
class ToolCall:
    tool_name: str
    params: dict
    call_id: str

@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)

@dataclass
class CheckResult:
    passed: bool
    reason: str | None = None
```

---

## 5. ToolInjector 接口

> 实现细节见 [tool-system.md](./tool-system.md)

```python
class ToolInjector:
    """根据意图动态注入工具到 LLM 上下文"""

    def __init__(self, registry: dict[str, BaseTool],
                 routing_rules: list[RoutingRule],
                 max_tools_per_turn: int = 5):
        self._registry = registry
        self._routing_rules = routing_rules
        self._max_tools = max_tools_per_turn

    async def inject(self, intent: Intent, context: SessionContext) -> list[BaseTool]:
        """过滤链：意图匹配 → 场景过滤 → 权限过滤 → 数量截断。
        返回 <= max_tools_per_turn 个工具实例。
        Raises: ToolError 意图匹配不到任何工具时
        """

    async def inject_definitions(self, intent: Intent,
                                  context: SessionContext) -> list[ToolDefinition]:
        """inject() 后转为 ToolDefinition 列表，直接传给 LLM。"""
        tools = await self.inject(intent, context)
        return [t.to_definition() for t in tools]
```

```python
@dataclass
class RoutingRule:
    intent_patterns: list[str]      # 英文标识，支持通配符 "query_*"
    scenario: str | None            # 场景过滤（None = 全场景）
    tools: list[str]                # 工具名列表
    priority: int = 0               # 优先级，高优先
```

---

## 6. Channel Adapter 接口

> 实现细节见 [conversation-ux.md](./conversation-ux.md)

### 6.1 ChannelMessage

```python
@dataclass
class ChannelMessage:
    """渠道适配后的输出"""
    channel: str                    # "web" | "wechat" | "miniprogram" | "app"
    content_type: str               # 渠道原生内容类型
    payload: dict                   # 渠道原生格式
    was_downgraded: bool = False    # 是否经过降级
    original_type: str | None = None  # 降级前的 message_type
```

### 6.2 ChannelAdapter ABC

```python
class ChannelAdapter(ABC):
    """渠道适配器 — 负责消息格式转换和能力降级"""

    @abstractmethod
    def adapt(self, message: AgentMessage) -> ChannelMessage:
        """将统一消息格式转换为目标渠道格式。
        Raises: ChannelError 不支持的 message_type（应先调用 adapt_with_fallback）
        """

    @abstractmethod
    def get_capabilities(self) -> ChannelCapabilities:
        """声明渠道支持的消息类型。"""

    @abstractmethod
    def downgrade(self, message: AgentMessage) -> ChannelMessage:
        """将不支持的消息类型降级为该渠道可用的最接近格式。
        降级链：原始类型 → text（最终兜底）。
        """

    def adapt_with_fallback(self, message: AgentMessage) -> ChannelMessage:
        """自动降级：支持则 adapt，否则 downgrade。"""
        if message.message_type in self.get_capabilities().supported_types:
            return self.adapt(message)
        return self.downgrade(message)
```

```python
@dataclass
class ChannelCapabilities:
    supported_types: list[str]      # 该渠道支持的 message_type 列表
    supports_rich_text: bool
    supports_images: bool
    supports_forms: bool
    max_message_length: int
```

---

## 7. ScenarioFSM 接口

### 7.1 ScenarioFSM ABC

```python
class ScenarioFSM(ABC):
    """业务场景状态机"""

    name: str
    states: list[str]
    transitions: list[Transition]
    timeout_seconds: int = 300

    @abstractmethod
    def get_initial_state(self) -> str:
        """返回初始状态。"""

    @abstractmethod
    def get_allowed_transitions(self, current_state: str) -> list[Transition]:
        """返回当前状态允许的转换。"""

    def can_transition(self, current_state: str, trigger: str,
                       context: SessionContext) -> bool:
        """检查转换是否允许（含 guard 校验）。"""
        for t in self.get_allowed_transitions(current_state):
            if t.trigger == trigger:
                if t.guard is None or t.guard(context):
                    return True
        return False
```

### 7.2 Transition 与回调签名

```python
@dataclass
class Transition:
    from_state: str
    to_state: str
    trigger: str                    # 触发事件名
    guard: Callable[[SessionContext], bool] | None = None
    action: Callable[[SessionContext], Awaitable[SessionContext]] | None = None

# ScenarioFSM 回调签名
EntryAction = Callable[[SessionContext], Awaitable[SessionContext]]
ExitAction = Callable[[SessionContext], Awaitable[None]]
TimeoutAction = Callable[[SessionContext], Awaitable[AgentMessage]]
```

---

## 8. ContextManager 接口

> 实现细节见 [context-manager.md](./context-manager.md)

```python
class ContextManager(ABC):
    """上下文管理器 — 负责会话上下文的生命周期管理"""

    @abstractmethod
    async def load(self, session_id: str) -> SessionContext:
        """加载会话上下文。不存在则创建新的。
        Raises: ContextError 存储层故障时
        """

    @abstractmethod
    async def save(self, context: SessionContext, response: AgentMessage) -> None:
        """保存上下文更新（追加消息、更新槽位、更新 FSM 状态）。
        Raises: ContextError 存储层故障时
        """

    @abstractmethod
    async def compress(self, context: SessionContext) -> SessionContext:
        """压缩上下文：滑动窗口 + LLM 摘要。
        触发条件：history_tokens > token_budget * history_ratio。
        返回新的 SessionContext（不修改原始对象）。
        """

    @abstractmethod
    def get_token_budget(self, context: SessionContext) -> TokenBudget:
        """计算当前 Token 预算分配。"""

    @abstractmethod
    async def update_slots(self, context: SessionContext,
                           new_entities: dict) -> SessionContext:
        """更新实体槽位。合并新实体到现有槽位。
        返回新的 SessionContext（不修改原始对象）。
        """
```

```python
@dataclass
class TokenBudget:
    """Token 预算分配"""
    total: int                      # Provider max_context_tokens
    system_prompt: int              # 20%
    history: int                    # 50%
    tool_results: int               # 20%
    slot_entities: int              # 10%
    history_used: int               # 当前 history 实际占用
    needs_compression: bool         # history_used > history
```

---

## 9. IntentEngine 接口

> 实现细节见 [intent-engine.md](./intent-engine.md)

```python
class IntentEngine(ABC):
    """意图识别引擎 — 三级级联"""

    @abstractmethod
    async def classify(self, message: UserMessage,
                       context: SessionContext) -> Intent:
        """识别用户意图。
        级联顺序：规则匹配 → 语义检索 → LLM 分类。
        每级不满足置信度阈值则升级。
        全部失败返回兜底 Intent(name="fallback", confidence=0.0)。
        Raises: IntentError 所有级别均异常时
        """

    @abstractmethod
    def get_supported_intents(self) -> list[IntentInfo]:
        """返回所有已注册意图的元信息。"""

    @abstractmethod
    async def add_samples(self, intent_name: str,
                          samples: list[str]) -> None:
        """添加意图样本（用于规则/语义检索优化）。"""
```

```python
@dataclass
class IntentInfo:
    name: str                       # 英文标识
    display_name: str               # 中文展示名
    description: str
    sample_count: int               # 已注册样本数
    typical_entities: list[str]     # 常见实体字段
```

---

## 10. Strategy 接口

> 策略引擎决定"下一步做什么"：直接回复、调用工具、发起确认、切换场景等。

```python
class Strategy(ABC):
    """策略决策引擎"""

    @abstractmethod
    async def decide(self, intent: Intent, context: SessionContext,
                     tools: list[BaseTool]) -> Action:
        """根据意图和上下文决定下一步动作。
        Raises: OpenChatShopError 无法决策时
        """
```

```python
@dataclass
class Action:
    """策略输出的动作"""
    type: Literal["reply", "tool_call", "confirm", "clarify",
                  "transfer", "switch_scenario", "end"]
    payload: dict
    # reply: {"content": str, "message_type": str}
    # tool_call: {"tool_name": str, "params": dict, "call_id": str}
    # confirm: {"title": str, "description": str, "pending_action": Action}
    # clarify: {"question": str, "missing_slots": list[str]}
    # transfer: {"reason": str, "department": str}
    # switch_scenario: {"scenario": str, "trigger": str}
    # end: {"summary": str}
```

---

## 11. 对话编排器主流程

```python
class DialogueOrchestrator:
    """对话编排器 — 协调所有模块"""

    def __init__(self, ...):
        self._session_locks: dict[str, asyncio.Lock] = {}

    async def handle_message(self, message: UserMessage) -> AgentMessage:
        """处理用户消息，返回 Agent 回复。
        同一 session_id 串行处理（异步锁保护）。
        """
        lock = self._session_locks.setdefault(message.session_id, asyncio.Lock())
        async with lock:
            return await self._handle_message_internal(message)

    async def _handle_message_internal(self, message: UserMessage) -> AgentMessage:
        # 1. 安全检测
        try:
            self.security.check(message)
        except SecurityError as e:
            self._audit_log("security_blocked", message, e)
            return self._error_response("安全检测未通过，请修改后重试。")

        # 2. 加载上下文
        try:
            context = await self.context_manager.load(message.session_id)
        except ContextError:
            return self._error_response("会话已过期，请重新开始。")

        # 3. 意图识别（级联，内部处理降级）
        intent = await self.intent_engine.classify(message, context)

        # 4. 动态注入工具
        tools = await self.tool_injector.inject(intent, context)

        # 5. 策略决策
        action = await self.strategy.decide(intent, context, tools)

        # 6. 执行动作
        response = await self._execute_action(action, context, tools)

        # 7. 更新上下文
        await self.context_manager.save(context, response)

        return response

    async def _execute_action(self, action: Action,
                               context: SessionContext,
                               tools: list[BaseTool]) -> AgentMessage:
        """根据 Action.type 分发执行。"""
        match action.type:
            case "reply":
                return AgentMessage(
                    message_type=action.payload.get("message_type", "text"),
                    payload=action.payload,
                    text_fallback=action.payload.get("content", ""),
                )
            case "tool_call":
                return await self._execute_tool(action, context, tools)
            case "confirm":
                return AgentMessage(
                    message_type="confirm",
                    payload=action.payload,
                    text_fallback=action.payload.get("description", ""),
                    requires_confirmation=True,
                )
            case "clarify":
                return AgentMessage(
                    message_type="text",
                    payload=action.payload,
                    text_fallback=action.payload.get("question", ""),
                    suggestions=self._build_clarify_suggestions(action),
                )
            case "transfer":
                return AgentMessage(
                    message_type="transfer",
                    payload=action.payload,
                    text_fallback="正在为您转接人工客服...",
                )
            case "switch_scenario":
                context.current_scenario = action.payload["scenario"]
                return await self._handle_scenario_switch(action, context)
            case "end":
                return AgentMessage(
                    message_type="text",
                    payload={"content": action.payload.get("summary", "")},
                    text_fallback=action.payload.get("summary", ""),
                )

    async def _execute_tool(self, action: Action,
                             context: SessionContext,
                             tools: list[BaseTool]) -> AgentMessage:
        """执行工具调用，含校验、前置检查、重试和补偿逻辑。"""
        tool = next((t for t in tools if t.name == action.payload["tool_name"]), None)
        if tool is None:
            raise ToolError(
                f"工具 {action.payload['tool_name']} 未注入",
                action.payload["tool_name"],
            )

        # 参数校验
        validation = tool.validate(action.payload["params"])
        if not validation.valid:
            return AgentMessage(
                message_type="text",
                payload={"content": f"参数校验失败：{'; '.join(validation.errors)}"},
                text_fallback=f"参数校验失败：{'; '.join(validation.errors)}",
            )

        # 前置检查
        check = await tool.pre_check(action.payload["params"], context)
        if not check.passed:
            return AgentMessage(
                message_type="text",
                payload={"content": check.reason or "前置条件不满足"},
                text_fallback=check.reason or "前置条件不满足",
            )

        # 执行（失败时自动补偿）
        try:
            result = await tool.execute(action.payload["params"], context)
        except ToolError:
            await tool.compensate(action.payload["params"], context)
            raise

        return self._tool_result_to_message(result, action.payload["tool_name"])
```

---

## 12. 消息类型清单

所有渠道共享的 `message_type` 枚举。各渠道通过 ChannelAdapter 降级。

| message_type | 描述 | 必需字段 (payload) |
|-------------|------|-------------------|
| `text` | 纯文本回复 | `content: str` |
| `product_card` | 商品推荐卡片 | `product_id, name, price, image_url, actions[]` |
| `product_list` | 多商品推荐 | `products: list[product_card], total` |
| `order_card` | 订单摘要 | `order_id, status, items[], total_amount` |
| `logistics_timeline` | 物流追踪 | `order_id, steps[{status, time, location}]` |
| `confirm` | 操作确认 | `title, description, confirm_label, cancel_label` |
| `form` | 信息收集表单 | `fields[{name, type, label, required, options?}]` |
| `rating` | 满意度评分 | `prompt, max_score` |
| `transfer` | 转人工提示 | `reason, estimated_wait_seconds` |
| `carousel` | 轮播信息 | `items[], auto_play, interval_ms` |
| `quick_replies` | 快捷回复建议 | `options[{label, value}]` |

---

## 13. 配置 Schema 规范

所有 YAML 配置文件遵守以下规则：

- **required** 字段缺失时启动报错，不使用默认值
- **optional** 字段标注默认值
- 所有配置文件通过 Pydantic Model 校验

```python
# 配置校验基类
class BaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 禁止未知字段
```

### 13.1 Provider 配置

```yaml
# configs/providers.yaml
providers:                            # required, 至少 1 个
  - name: string                      # required, 唯一标识
    type: string                      # required, "openai" | "anthropic" | "ollama" | ...
    model: string                     # required
    api_key_env: string               # required, 环境变量名
    api_base: string | null           # optional, default: null
    max_context_tokens: int           # optional, default: 4096
    capabilities:                     # optional, default: 自动检测
      tool_calling: bool              # optional, default: true
      streaming: bool                 # optional, default: true
      vision: bool                    # optional, default: false

cascade:                              # required
  levels:                             # required, 至少 1 级
    - provider: string                # required
      confidence_threshold: float     # required, 0.0-1.0
      timeout_seconds: int            # optional, default: 5
  fallback_provider: string           # required
```

### 13.2 工具路由配置

```yaml
# configs/tool_routing.yaml
max_tools_per_turn: int               # optional, default: 5

rules:                                # required, 至少 1 条
  - intent_patterns: [string]         # required, 英文标识，支持 "query_*"
    scenario: string | null           # optional, default: null (全场景)
    tools: [string]                   # required, 工具名列表
    priority: int                     # optional, default: 0
```

---

## 14. 日志与追踪规范

### 14.1 结构化日志

所有模块必须输出结构化日志，包含以下字段：

```python
{
    "timestamp": "ISO 8601",
    "level": "DEBUG | INFO | WARN | ERROR",
    "module": "provider | context | intent | tool | security | channel | orchestrator",
    "trace_id": "string",           # OpenTelemetry trace ID
    "span_id": "string",            # OpenTelemetry span ID
    "session_id": "string | null",
    "event": "string",              # 事件名
    "duration_ms": "int | null",    # 操作耗时
    "details": {}                   # 事件相关数据
}
```

### 14.2 Trace Span 命名

| Span 名称 | 所属模块 | 记录内容 |
|-----------|---------|---------|
| `orchestrator.handle_message` | 编排器 | 总耗时、各步骤耗时 |
| `provider.chat` | Provider | 模型名、token 用量、耗时 |
| `provider.cascade` | Provider | 各级尝试、最终命中级别 |
| `context.load` | 上下文 | 会话 ID、历史消息数 |
| `context.compress` | 上下文 | 压缩前/后 token 数 |
| `intent.classify` | 意图 | 级联级别、最终意图、置信度 |
| `tool.inject` | 工具注入 | 意图、注入工具列表 |
| `tool.execute` | 工具 | 工具名、参数、耗时、成功/失败 |
| `security.check` | 安全 | 检测结果、是否拦截 |
| `channel.adapt` | 渠道 | 原始类型、输出类型、是否降级 |

### 14.3 审计日志

写操作和敏感操作必须额外记录审计日志：

```python
{
    "audit": true,
    "action": "tool.execute",
    "tool_name": "string",
    "user_id": "string",
    "session_id": "string",
    "params": {},                   # 脱敏后的参数
    "result": "success | failure",
    "timestamp": "ISO 8601"
}
```
