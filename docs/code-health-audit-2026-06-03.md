# OpenChatShop 全量健康审查 + 业界对标 + 改进路线

> 出具人：首席架构师 · 日期：2026-06-03
> 项目：OpenChatShop（模型无关的开源电商智能对话系统）
> 审查基准：逐文件核实 + 8 维度对抗式验证 + 2025/2026 业界最佳实践对标
> 原则：诚实优先，遵守项目 CLAUDE.md「失败要响亮」——优点给够，问题不掩盖。

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [健康度评分](#2-健康度评分)
3. [真实优点](#3-真实优点)
4. [最重要的「不和谐之处」（按严重度排序）](#4-最重要的不和谐之处按严重度排序)
5. [改进路线（P0/P1/P2）](#5-改进路线-p0p1p2)
6. [速赢清单（Quick Wins）](#6-速赢清单quick-wins)
7. [对标一线产品的进化方向](#7-对标一线产品的进化方向)
8. [附录：验证方法](#8-附录验证方法)

---

## 1. 执行摘要

**这个项目到底什么水平？** OpenChatShop 是一个**「演示级实现套了生产级外壳」**的项目，而非真生产级。

工程外壳确实达到了一线开源项目的样子：清晰的分层架构、872 个测试函数、FastAPI + React 双前端、Docker/nginx 部署清单、OWASP 安全意识、以及弹性/可观测性/成本治理/评测飞轮等完整命名的子系统。CLAUDE.md 的工程治理纪律（plan-before-code、evidence required、失败要响亮）也相当成熟。**作为教学/脚手架项目，质量在线。**

**但最大的结构性问题是「宣称与接线系统性脱节」**——大量子系统被定义、被测试、被文档标注为「运行中」，却在生产路径上零调用或接错目标：

| 子系统 | 宣称 | 实际 | 证据 |
|--------|------|------|------|
| 弹性容错 | 熔断+重试保护 LLM 调用 | 包裹不存在的 `provider.generate`，AttributeError 被 `except:pass` 吞掉，连带跳过 `set_provider` | `main.py:317/325` |
| 安全防御 | 四层（注入→PII脱敏→RBAC→输出脱敏） | 仅注入检测一层硬阻断；PII 只记日志不脱敏；RBAC/脱敏层零调用 | `security.py:323/331` |
| 评测飞轮 | golden 回归保护意图准确率 | 0/500 全 FAIL（payload 键名契约错位），且 CI 根本不跑 | `evaluation/__main__.py:59` |
| 成本治理 | 预算护栏+告警 | 记 `prompt_tokens=0` + 固定 `100/轮` 假数据 | `orchestrator.py:688` |
| Level-2 语义 | 90% 请求低成本解决 | 中文 `split()` 得单 token，Jaccard 恒 0，级联退化为两级 | `intent.py:195` |
| ScenarioFSM | 状态机管控退款/投诉 | 约 249 行从未被驱动 | `orchestrator.py:490` |

**更危险的是一个真实可利用的最高危漏洞**：无订单归属校验（IDOR / OWASP API#1 BOLA），任意已认证用户凭枚举 `order_id` 即可查询/退款/取消他人订单，且 `user_id` 来自客户端不可信输入（`query_order.py:37`、`create_refund.py:49`、`cancel_order.py:39` 四个工具均无 owner 校验）。

叠加 `entrypoint.sh`/`deploy/` 未提交但被 Dockerfile/README 硬依赖、`.dockerignore` 与 Dockerfile 对 `frontend-agent` 互斥——**干净克隆后 `docker build` 必然失败**，部署链路从未被端到端验证。

**诚实结论：** 架构骨架和工程意识值得肯定；但若直接上生产，存在**数据越权、弹性失效、安全防御名不副实、成本护栏空转、评测无法回归**五重风险。所幸这些缺陷绝大多数是「接线/契约」问题（effort 多为 low/medium），骨架正确、修复路径清晰，不是地基塌方式的重写。距离真生产级还有**一轮扎实的「接线对齐 + 安全补全」工作量**，而非表面功能堆叠。

---

## 2. 健康度评分

### **52 / 100**

**为何是 52：** 工程外壳和架构意识在水准线以上（撑起约 50 分基础盘），但生产关键路径存在系统性「定义了未接线/接错线」缺陷和一个可利用的 CRITICAL 数据越权漏洞，强力压制评分。

- **加分项**：分层清晰、模块化合理、872 个真实测试、双前端、Docker/可观测性/弹性/评测子系统齐备、OWASP 与 fail-closed 意识、CLAUDE.md 治理严谨。
- **扣分项**：(1) CRITICAL IDOR——电商系统最高危；(2) 六大子系统生产路径零生效，宣称严重背离实现；(3) docker build 必然失败 + 关键运维文件未提交；(4) PII 明文落库/发外部 LLM/回包（OWASP LLM02）。
- **为何不是 40 以下**：缺陷绝大多数是「接线/契约」问题，effort 多为 low/medium，骨架正确、修复路径清晰。一轮聚焦修复后合理可达 **75+**。

---

## 3. 真实优点

这些不是客套，是逐文件核实后确认的工程实力：

1. **架构分层清晰、职责切分到位**：`core`(orchestrator/intent/strategy/security)、`tools`、`storage`(三后端)、`observability`、`evaluation`、`channels` 各司其职，模块化达到一线开源项目水准。
2. **测试规模真实可观**：872 个测试函数、45 个测试文件，覆盖单元/集成/E2E/load 四层。这不是装样子——多数纯逻辑测试扎实（如 `resilience.py` 熔断器状态机本身实现正确）。
3. **基础设施组件「实现质量」本身是对的**：CircuitBreaker 三态机、RetryPolicy 指数退避、令牌桶限流、Redis 上下文后端等组件单独看符合业界 SRE 实践——问题出在接线而非组件。
4. **安全意识在框架层面存在**：入站 XML 用 defusedxml 防 XXE、JWT fail-closed 方向正确、注入检测硬抛 SecurityError。意识到位，只是落地不完整。
5. **模型无关设计方向正确**：`LLMProvider` ABC + 多 provider + `CascadeStrategy` 骨架，符合「编排逻辑与模型解耦」的最佳实践，为对标 Sierra 星座模型留了正确扩展点。
6. **工程治理规范严格**：CLAUDE.md 的 plan-before-code、一次一个 feature、evidence required 纪律 + 跨会话连续性机制，远超一般个人项目。
7. **产品完整度高**：双前端 + 11 种富消息 + 人工坐席后台 + WebSocket 转接，产品形态接近真实电商客服。
8. **可观测性/评测/成本治理的「设计意图」对标业界正确方向**：tracing、golden dataset、LLM-as-judge、cost tracker 概念落地——虽接线断了，但方向与 Langfuse/Braintrust/OpenTelemetry GenAI 一致，骨架可复用。

---

## 4. 最重要的「不和谐之处」（按严重度排序）

### 🔴 CRITICAL-1：无订单归属校验（IDOR/BOLA）——任意用户可越权操作他人订单

- **Where**：`src/open_chat_shop/tools/builtin/query_order.py:37`、`cancel_order.py:39/53`、`create_refund.py:49/61`（四工具均 `self._order_repo.get(order_id)` 直查，无 `context.user_id` owner 校验）；`user_id` 来自客户端 `api/app.py` 的 `ChatRequest`，`auth.py` 未将 JWT sub 绑定 session。
- **Why**：OWASP API#1 BOLA / LLM06 Excessive Agency 的典型最高危漏洞。已认证用户只要枚举 `ORD-xxxx` 即可读取他人订单全字段、发起退款、改收货地址，造成直接财务损失和数据泄露。且 `user_id` 来自不可信客户端输入，即便加 owner 校验也需先修复来源。业界（Decagon/Salesforce）一致要求工具层最小权限 + 服务端身份绑定。
- **Fix**：(1) JWT 解码后将 sub 写入 `request.state`，构造 `UserMessage` 时携带服务端 `user_id`；(2) 工具 `execute/pre_check` 强制 owner 校验 `order=repo.get_for_user(order_id, context.user_id); if not order: return 错误('订单不存在')`（用「不存在」防枚举）；(3) Repository 提供 `get_for_user` 收口。

### 🔴 CRITICAL-2：弹性层是死代码——熔断+重试包裹了不存在的 `provider.generate`

- **Where**：`main.py:317` `original_generate = provider.generate`（`LLMProvider` 只有 chat/stream/embed，见 `core/provider.py:24-61`）；`main.py:325-326` `except Exception: pass` 吞掉 AttributeError，同 try 块内的 `orchestrator.set_provider(provider)` 随之被跳过。
- **Why**：三重违背——(1) 求值 `provider.generate` 立即抛 AttributeError，CircuitBreaker+RetryPolicy 对象创建后被丢弃，真实 LLM 调用走 `orchestrator.py:681/736` 的 `provider.chat()`，零熔断零重试；(2) bare `except:pass` 把接线损坏静默化（违反 Rule 12）；(3) `set_provider` 被跳过意味着 orchestrator 可能以 `_provider=None` 运行，LLM 增强退化为模板回复。业界（LiteLLM/Maxim AI）将熔断/退避列为生产 LLM 服务必选项。
- **Fix**：改为 `original_chat = provider.chat; provider.chat = _resilient_chat`；删 `except:pass` 改 `logger.exception`；`set_provider` 移出 try 块无条件执行；补集成测试（注入抛 TimeoutError 的 provider，断言重试触发、5 次失败后断路器 OPEN）。

### 🔴 CRITICAL-3：干净克隆后 docker build 必然失败

- **Where**：`entrypoint.sh`、`deploy/`（git ls-files 为空，均未提交）但 `Dockerfile:41/50` COPY+ENTRYPOINT 硬依赖、README 把 `deploy/nginx.conf` 当生产入口；`.dockerignore:19` 排除 `frontend-agent/` 但 `Dockerfile:6/12/15/35` 又 COPY 并 `npm run build` 该目录。
- **Why**：构建清单（已提交）与依赖资源（未提交）不同步，任何 CI/同事从 origin/main 克隆后 `docker build` 在 `COPY entrypoint.sh` 处中断；`.dockerignore` 剔除 frontend-agent 又要 COPY 它，产出空 dist。容器化部署链路从未被端到端验证。额外：`entrypoint.sh` 的 `alembic upgrade head || echo continuing` 与 `set -e` 语义矛盾，迁移失败仍启动，schema 不一致风险高。
- **Fix**：(1) `git add entrypoint.sh deploy/`；(2) 统一 `.dockerignore` 与 Dockerfile 对 frontend-agent 口径；(3) 去掉迁移 `|| echo continuing`（如需软启动用显式 `ALLOW_MIGRATION_SKIP=1`）；(4) CI 增加 docker build 冒烟。

### 🔴 CRITICAL-4：回归评测框架 0/500 全 FAIL 且不接 CI

- **Where**：`evaluation/__main__.py:59` 读 `payload.get('intent_name')/('tool_name')`，但 `tool_response_mapper` 构造的成功 payload 不含这两个 key；`strategy.py` 的 `intent_name` 只在 `_pending_action` 子字典；CI（`.github/workflows/ci.yml:41`）只跑 pytest，无 evaluation step 也无 `--cov-fail-under`。
- **Why**：仓库唯一对 intent/工具路径做回归的机制，却因键名契约错位使 `actual_intent` 恒空、500 条全 FAIL，且 0% 通过率永远不阻断合并。更糟的是 `test_evaluation_cli.py:56` 的「end-to-end」单测手工注入正确答案（绕过真实提取逻辑），把 0/500 bug 完全掩盖，属于误导性断言。4204 行 golden 数据测不出真东西。业界（Braintrust/Intercom）将 golden 回归作为 deployment blocking 门槛。
- **Fix**：(1) `AgentMessage` 增加结构化 `meta` 字段由 orchestrator 显式填充，evaluation 从 meta 读；(2) ci.yml 加 `python -m open_chat_shop.evaluation regression` 并设 `pass_rate≥0.6` 门槛；(3) `test_evaluation_cli` 改真端到端，删误导性注释。

### 🟠 HIGH-5：四层安全防御名不副实——RBAC/脱敏层零调用，PII 只记日志

- **Where**：`core/security.py:323` `check_permission`、`:331` `sanitize_output` 在 src/ 全树零调用方（`orchestrator.py:165` 只调 `check_input`）；`check_input`（security.py:295-321）对 PII 仅 `logger.info`，masked 文本不回写，下游用原始 content 发 LLM/存历史。
- **Why**：README:56/287 宣称四层防护，实际只有第1层注入检测真阻断，第2层退化为日志、第3/4层完全死代码。PII 明文落入 Redis/DB 历史、明文发外部 LLM（LiteLLM 可指任意 base_url）、明文经 WeChat 回包，违反 OWASP LLM02。业界（Salesforce Einstein Trust Layer/Decagon）在数据到达 LLM 前强制脱敏。
- **Fix**：二选一对齐文档——(A) 真接线：`check_input` 回写 masked content，工具执行前调 `check_permission`，写操作结果调 `sanitize_output`；(B) 短期不实现则 README 降级为两层，删除四层/RBAC/脱敏宣称。

### 🟠 HIGH-6：DB/Redis 后端丢失 mode 和 human_agent_id——人工会话被机器人抢答

- **Where**：`storage/redis_context.py` 序列化/反序列化零 mode/human_agent_id 引用；`storage/db_context.py:86/172/207` 重建 `SessionContext` 缺失；而 `core/context.py:115-116` InMemory 完整保留，实现间不对称。
- **Why**：orchestrator 人工模式守卫依赖 `context.mode`；生产路径用 DB/Redis 后端时，跨请求 mode 被 dataclass 默认值复位为 AI_MODE，导致已转人工会话被 AI 抢答——坐席接管在生产后端下失效。根因是全仓 5+ 处手工逐字段抄写 SessionContext，演化必然遗漏。
- **Fix**：在 redis/db 序列化反序列化补上两字段；全仓 SessionContext 重建统一改 `dataclasses.replace()`；补「转人工后 DB 后端跨请求保持 HUMAN_MODE」回归测试。

### 🟠 HIGH-7：成本治理空转——记录假数据，护栏无法检测失控循环

- **Where**：`orchestrator.py:688` `cost_tracker.record(model='unknown', prompt_tokens=0, completion_tokens=0)`；`middleware.py:152` `cost = payload.get('token_usage', self._default_cost)`，全仓无任何地方写 token_usage，恒扣 `default_cost=100`。
- **Why**：成本本应确定可计算，却用 0 和常量占位，使整套预算告警空转。业界（Maxim AI/Google Cloud SRE）指出 Agent 最危险成本风险是失控循环（4K token 第 5 步膨胀至 128K，成本 32 倍），无真实归因则护栏不触发。违反 Rule 12。
- **Fix**：`orchestrator._llm_enhance` 读取 `response.usage` 写入 `payload['token_usage']` 并传 `cost_tracker.record`；对齐 OpenTelemetry GenAI 语义约定（`gen_ai.usage.input_tokens/output_tokens`）。

### 🟠 HIGH-8：Level-2 语义匹配对中文完全失效——三级级联退化为两级

- **Where**：`core/intent.py:195` `text_words = set(text.lower().split())`——中文无空格整句成单 token，「我想查询我的订单」与「查询订单」Jaccard=0.0；`intent.py:208` `best_score > 0` 永远 False；`semantic_search.py` 向量栈是孤儿模块从未接入。
- **Why**：面向中文电商，三级级联核心价值是让 90% 请求在低成本 Level-2 解决（README:310 宣称）。实际中文路径 Level-2 系统性返回 0，所有非规则命中请求升级到 Level-3 LLM，与省钱叙事矛盾。业界（semantic-router）嵌入路由精度 92-96%，此处中间层完全空转。
- **Fix**：短期用字符级 bigram 重叠替代 whitespace split；中期接 jieba/真实 embedding（LiteLLMProvider.embed 已实现）；补中文语义相近短语命中测试。

### 🟠 HIGH-9：高风险写操作的二次确认是断头路

- **Where**：`strategy.py:114-127` requires_confirmation 工具返回 `type='confirm'`，payload 塞 pending_action；`orchestrator.py:269` 只在 `action.type=='clarify'` 时存入 slots，confirm 分支不触发；用户回「是」时从零重新分类。
- **Why**：`create_refund`/`cancel_order`/`modify_address` 的确认门控形同虚设——用户确认后操作执行不到（流程卡死），或被重新识别为退款跳过确认直接执行。对比 clarify 有完整 `_pending_action` 闭环（orchestrator.py:215-240），confirm 无对应处理。业界（OWASP AI Agent Cheat Sheet/Decagon）要求高风险不可逆操作有服务端状态门控。
- **Fix**：命中 requires_confirmation 时持久化一次性 confirmation_token（tool_name+params 指纹+TTL）；下一轮检测肯定/否定意图执行或丢弃；高额退款走人工审批队列；补端到端测试。

### 🟠 HIGH-10：原生 function-calling 全链路被旁路

- **Where**：`orchestrator.py:681/736` 两处 `provider.chat(messages)` 均无 `tools=`；`anthropic_provider.py` chat 接受 tools 但不使用、硬编码 `tool_calls=[]`、`get_capabilities` 返回 `tool_calling=False`；工具选择全由 `strategy.py:48-144` 的 4 层 if/else 处理。
- **Why**：8 个工具规模完全适合原生 FC（2025 业界共识）。当前架构承担自造路由全部成本却没拿到结构化 inputs/outputs、可追溯 call_id、error schema 收益；Level-3 还额外引入自由文本 LLM 分类（`intent.py:245` 固定置信度 0.75、精确字符串匹配，模型回带标点即 fail）。
- **Fix**：ToolDefinition 通过 `tools=` 传给 provider.chat，消费 `LLMResponse.tool_calls`；保留 RuleBasedMatcher 仅做 Level-1 过滤，删除 strategy if-else 工具映射；AnthropicProvider 实现真实 tool_use 解析或文档标注不支持。

> **其余已确认但严重度较低的问题**（MEDIUM/LOW）：CascadeStrategy 未实例化、context.user_role 硬编码 customer、YAML RBAC 结构错配静默回退、confirm 服务端无门控、JWT except 过宽、WeChat 出站 CDATA 注入、AuditLogger/CostTracker 三处 `except:pass`、golden_dataset.py 4204 行违反 800 上限、estimate_tokens //2 vs //4 漂移、两个 _llm_enhance system_prompt 重复、InMemoryOrderRepository 就地 mutate、slots 原地 mutate 违反不可变、两前端 rich/ 组件漂移、ChatMessage 同名异构、三套前端配色冲突、frontend-agent lint 跑不通、.vite/ 入库 + 截图入库 + 空壳目录、测试徽章 839 vs 实际 872、ResponseCache._make_key 无兜底、LLM judge 无量表裁剪、golden 断言阈值 ≥50 vs 实际 500、attack 样本期望语义错误、三套 _build_orchestrator 漂移无 conftest、上下文压缩占位从不触发、Level-3 固定置信度、judge family bias。完整清单见结构化输出 top_discordances 与 roadmap。

---

## 5. 改进路线（P0/P1/P2）

### P0-A：堵住可利用漏洞 + 恢复部署可用性（红线）
- **Items**：修 IDOR（user_id 服务端化 + 工具 owner 校验）｜提交 entrypoint.sh/deploy 并统一 Docker 口径、去掉迁移软失败｜修弹性接线（包裹 chat + 删 except:pass + set_provider 移出 try）｜PII 真脱敏回写下游/历史/LLM｜WeChat 出站 XML 用 ElementTree 防 CDATA 注入。
- **Impact**：消除唯一可利用的 CRITICAL 数据越权、让项目可被任何人 clone+build、生产 LLM 故障时真有熔断保护、停止 PII 明文外泄。「能不能上生产」的红线。
- **Effort**：medium（约 2-3 天，IDOR 需贯通 auth→message→tool 一条链）。

### P0-B：评测飞轮闭环 + 接入 CI
- **Items**：AgentMessage 加结构化 meta 字段修复 0/500 契约｜ci.yml 加 evaluation regression + `--cov-fail-under=80`｜test_evaluation_cli 改真端到端｜attack 样本加 expected_blocked。
- **Impact**：4204 行 golden 从「测不出真东西」变成「契约破裂立刻 RED」，prompt/模型变更有 deployment blocking。从演示级走向可持续迭代的地基。
- **Effort**：medium（约 2-3 天）。

### P1-A：宣称与实现对齐——消除死代码（遵守 Rule 7 二选一）
- **Items**：SecurityGuard 四层｜ScenarioFSM 子系统｜confirm 闭环｜成本治理真实化｜renderers.py/semantic_search.py/SlotTracker 空壳｜数据飞轮持久化（DatabaseAuditLogger/CostTracker）。每个子系统要么真接线要么删除。
- **Impact**：消除「定义了未接线」的虚假健壮性，大幅降低维护者认知负担。健康度 52→70+ 的主路径。
- **Effort**：high（6+ 子系统，每个单独走 plan-before-code；约 1 周）。

### P1-B：意图路由现代化
- **Items**：Level-2 中文化（bigram/jieba/embedding）｜原生 FC（tools= 传 chat + AnthropicProvider 真实 tool_use）｜RuleBasedMatcher 仅做 Level-1｜Level-3 structured_output｜RBAC 主体真实化（JWT role）。
- **Impact**：对标 2025 业界共识，三级级联真省 token、工具调用拿到结构化收益、权限支持角色隔离。
- **Effort**：high（FC 改造需 provider 层真实实现；约 1 周）。

### P2：代码质量收口 + 前端去重 + 可观测性对标
- **Items**：golden_dataset 迁 JSON｜estimate_tokens 统一系数 + _llm_enhance 去重｜OrderRepository 不可变化｜两前端 rich/ 抽共享包 + types 下沉｜frontend-agent lint 补全 + .gitignore/.vite/截图清理｜judge 跨家族 + 越界裁剪 + OpenTelemetry GenAI 语义约定接 Langfuse/Phoenix。
- **Impact**：解决 800 行/不可变/DRY/前端漂移债务，评测器可信、可观测性对标业界。不阻塞上生产但提升长期健康度。
- **Effort**：medium（多为独立 low effort 清理，可并行；约 3-5 天）。

---

## 6. 速赢清单（Quick Wins）

低成本高收益，建议优先：

1. `main.py:317` 改 `provider.chat`，删 except:pass，set_provider 移出 try——一处改动恢复整条弹性链。`low/high`
2. `git add entrypoint.sh deploy/`；统一 .dockerignore 与 Dockerfile——让 docker build 可用。`low/high`
3. 工具层加 owner 校验（配合 user_id 服务端化）——堵 IDOR 第一闸。`low-medium/critical`
4. redis/db_context 补 mode + human_agent_id，统一 `dataclasses.replace()`——修人工会话被抢答。`low/high`
5. AuditLogger/CostTracker 三处 `except:pass` 改 `logger.exception`，security_event 用 ERROR——审计/成本写库失败不再静默。`low/medium`
6. `cache.py:44` json.dumps 加 `default=str`，键长提至完整 hexdigest——堵 TypeError + 降碰撞。`low/low`
7. ci.yml 加 `--cov-fail-under=80`，新建 tests/conftest.py 收敛三套 _build_orchestrator——覆盖率回归阻断合并。`low/medium`
8. README 三处「839 passing」改实际 872（或动态徽章），注明 3 个 skip——宣称对齐实际。`low/low`
9. 槽位提示文案三处收敛到 SlotTracker 单一来源；orchestrator import 已有 `_ORDER_ID_RE`——消除 DRY 漂移。`low/low`
10. auth.py JWT 校验收窄为 `except jose JWTError`，分级记日志，import 移顶部 fail-fast——签名伪造可审计区分。`low/medium`

---

## 7. 对标一线产品的进化方向

若要对标 **Sierra / Decagon / Intercom Fin** 这类一线产品，下一步可以这样进化（有想象力但能落地）：

1. **对标 Sierra「星座模型」编排**：当前单 provider + 自造 if-else 路由。演进为任务分层模型编排——意图分类用微调小模型（DistilBERT，10-20 个固定电商意图，准确率/延迟/成本均优于 LLM prompting），复杂推理走 Claude/GPT，工具执行用原生 FC。已有的 `CascadeStrategy` 骨架可作多 provider 故障转移落点。
2. **对标 Decagon/Intercom Fin 数据飞轮**：先打通最小闭环（meta 字段 + CI regression 门槛），再引入生产失败案例自动回流 golden set（Decagon 五组件飞轮入口）。
3. **对标 Salesforce Einstein Trust Layer 安全层**：(1) check_input 回写 masked content 全链路；(2) JWT sub 绑定 session + 工具 owner 校验；(3) 高风险写操作走服务端 confirmation_token + 人工审批队列。从「演示级安全」到「可审计安全」的关键跃迁。
4. **对标原生 function-calling 标准**：8 工具规模完全适合。把 ToolDefinition 通过 `tools=` 传 chat，消费 `tool_calls`，拿结构化 inputs/outputs、call_id、error schema。同时减少维护成本和幻觉率。
5. **对标 OpenTelemetry GenAI 语义约定**：已有 tracing 基础。对齐 `gen_ai.*` 标准属性，span 分层 `invoke_agent→chat→execute_tool`，接 Langfuse/Phoenix（开源自托管）。成本归因从「假数据」变 per-tenant 真实 FinOps。
6. **对标 Cresta 自动化边界发现**：attack 样本改 `expected_blocked=True`，从真实对话转录数据驱动地识别自动化边界，扩充对抗集参考 OWASP LLM01。
7. **真语义缓存 + 分级路由降本**：ResponseCache 升级为两层（精确 KV + 向量 cosine 阈值 0.90-0.95）+ Prompt 前缀缓存（静态在前动态在后）。Anthropic 缓存读取 $0.30/M vs 基础 $3.00/M，损益平衡仅 1.4 次读取，实测降推理成本 70%。
8. **FSM 子系统二选一并兑现**：若做有审计轨迹的退款/投诉多轮流程（业界共识：高风险合规流程用确定性工作流引擎而非纯 LLM），让 strategy 产出 switch_scenario + orchestrator 调 execute_transition 驱动；否则删除，承认多轮即 slot-filling。

---

## 8. 附录：验证方法

本报告所有 CRITICAL/HIGH 结论均经逐文件核实（非仅依赖 finding 描述）：

- `provider.generate` 不存在：`grep "def chat/stream/embed/generate" core/provider.py` 确认 ABC 及所有实现无 generate。
- IDOR：`grep user_id` 四个工具文件无 owner 校验输出。
- SecurityGuard 死层：`grep check_permission|sanitize_output` 排除 security.py 后零命中。
- 评测 0/500：核对 `__main__.py:59` 读 key 与 tool_response_mapper 产出 key 不匹配。
- 中文语义失效：核对 `intent.py:195` 的 `.split()` 逻辑。
- Docker/部署：`git ls-files entrypoint.sh deploy/` 返回空（未提交）。
- 测试数：`grep -rc "def test_"` = 872，README 标注 839（陈旧）。
- mode/human_agent_id 丢失：核对 redis/db_context 序列化无引用，InMemory（context.py:115）有引用。

业界对标依据：Sierra Constellation of Models、Decagon Security/Evaluation Engine、Intercom Fin AI Engine、Salesforce Agentforce/Einstein Trust Layer、Cresta、Google ADK、OWASP LLM Top 10 2025、OpenTelemetry GenAI Semantic Conventions、LiteLLM/Maxim AI 生产弹性指南、semantic-router、Braintrust/Langfuse 评测实践。

---

*报告结束。诚实优先——优点已给够，问题不掩盖。修复路径清晰，一轮聚焦的「接线对齐 + 安全补全」后，本项目合理可达 75+ 健康度。*