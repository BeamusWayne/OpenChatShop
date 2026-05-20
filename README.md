# OpenChatShop

模型无关的开源电商智能对话系统。通过统一的 LLM Provider 抽象层，一套代码适配 OpenAI、Anthropic、Qwen、DeepSeek、Ollama 等任意大语言模型后端，快速搭建生产级电商客服 Agent。

## 核心特性

- **模型无关** — Provider 抽象层解耦 LLM 依赖，YAML 配置切换模型，无需改代码
- **三级意图级联** — 规则匹配 → 语义检索 → LLM 分类，按置信度逐级升级
- **可插拔工具系统** — 8 个内置电商工具（订单/物流/商品/退款/转人工），自定义工具只需继承 `BaseTool`
- **四层安全防护** — Prompt 注入检测、内容安全过滤、RBAC 权限校验、输出脱敏
- **业务状态机** — 售前咨询/售后处理/退款流程独立 FSM，可编排组合
- **多渠道适配** — Web、小程序等渠道统一接口，11 种富消息类型渲染
- **生产就绪** — 速率限制、成本治理、会话持久化、OpenTelemetry 链路追踪、Docker Compose 一键部署

## 快速开始

### 环境要求

- Python 3.11+
- Redis（可选，用于会话持久化）
- PostgreSQL + pgvector（可选，用于向量检索）

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

服务启动后访问：
- 聊天界面: http://localhost:8000/
- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

### 配置 LLM Provider（可选）

默认使用规则引擎，无需 LLM。如需接入大模型提升智能度：

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

支持的环境变量：

| 变量 | 说明 | 必填 |
|------|------|------|
| `ANTHROPIC_API_KEY` | Anthropic / 智谱 GLM API Key | 接入 LLM 时必填 |
| `ANTHROPIC_BASE_URL` | 自定义 API 端点（默认 Anthropic 官方） | 否 |
| `GLM_MODEL` | 模型名称（默认 glm-5.1） | 否 |
| `OPENAI_API_KEY` | OpenAI API Key | 否 |

### Docker Compose

```bash
# 完整部署（api + redis + postgres）
docker compose up
```

## 项目结构

```
open-chat-shop/
├── main.py                     # 入口：组装组件并启动 FastAPI
├── run.sh                      # 启动脚本
├── pyproject.toml              # 项目依赖（FastAPI, LiteLLM, SQLModel, Redis...）
├── Dockerfile
├── docker-compose.yml          # api + redis + postgres
├── configs/                    # YAML 配置
│   ├── providers.yaml          # LLM Provider 配置
│   ├── tool_routing.yaml       # 工具路由规则
│   ├── security.yaml           # 安全策略
│   └── scenarios.yaml          # 业务场景 FSM
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
│   │   ├── orchestrator.py     # 对话编排器（主流程）
│   │   ├── security.py         # 安全防护层
│   │   ├── scenario.py         # 通用状态机 FSM
│   │   ├── slot_tracker.py     # 实体槽位追踪
│   │   ├── semantic_search.py  # 向量语义搜索
│   │   ├── cost_governance.py  # 成本治理
│   │   ├── rate_limiter.py     # 速率限制
│   │   ├── middleware.py       # 编排器中间件
│   │   └── handoff.py          # 人工转接队列
│   ├── tools/builtin/          # 8 个内置电商工具
│   ├── channel/                # 多渠道适配 + 富消息渲染
│   ├── api/                    # REST + WebSocket + 流式响应
│   ├── storage/                # 会话持久化（内存/Redis/数据库）
│   ├── evaluation/             # 评测框架（黄金数据集/回归/LLM-as-Judge）
│   └── observability/          # 日志/链路追踪
├── tests/                      # 39 个测试文件
├── static/                     # 前端聊天组件
└── docs/                       # 设计文档
```

## 内置测试数据

系统内置 mock 数据，启动即可体验全部功能，无需数据库。数据位于 `src/open_chat_shop/tools/builtin/_mock_data.py`。

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
| 可观测 | OpenTelemetry + structlog |
| 容器化 | Docker + Docker Compose |

## License

[Apache 2.0](LICENSE)
