# UX Review Report — OpenChatShop

> Reviewer: AI UX/Product/Engineering Review
> Date: 2026-05-20
> Status: In Progress (Iteration 1/5)

## Methodology

以新用户视角，从以下维度审查整个系统：

1. **首次体验 (FTUE)** — 新用户从 clone 到对话成功的路径
2. **对话质量** — 意图识别准确度、回复自然度、上下文延续
3. **错误处理** — 异常场景下的用户感知
4. **前端体验** — UI 可用性、交互流畅度、视觉一致性
5. **开发者体验** — API 设计、文档、部署流程

---

## Round 1 Findings

### CRITICAL — 阻断用户核心路径

| # | Issue | Severity | Category | Details |
|---|-------|----------|----------|---------|
| C1 | "查询订单 ORD-2024001" 返回 fallback | CRITICAL | 对话质量 | 规则匹配 query_order 但 confidence 低于 0.85 阈值，降级到 fallback |
| C2 | "搜索手机" 返回参数错误 | CRITICAL | 对话质量 | search_product 意图识别成功但实体提取缺失，tool 收到空 params |
| C3 | "我想买手机" 同 C2 | CRITICAL | 对话质量 | 同上 |

### HIGH — 严重影响用户体验

| # | Issue | Severity | Category | Details |
|---|-------|----------|----------|---------|
| H1 | static/index.html 无快速入口 | HIGH | FTUE | React 版有 QUICK_ACTIONS 但 HTML 版没有 |
| H2 | REST API 无对话上下文追踪 | HIGH | 对话质量 | 同 session_id 不共享状态 |
| H3 | 错误信息暴露技术细节 | HIGH | 错误处理 | `'order_id' is a required property` 用户无法理解 |
| H4 | 根路由冲突 | HIGH | 导航 | `@app.get("/")` 被 static mount 覆盖 |
| H5 | Mock 数据全英文 | HIGH | 本地化 | 面向中文用户却用英文名 |

### MEDIUM — 可用但有改进空间

| # | Issue | Severity | Category | Details |
|---|-------|----------|----------|---------|
| M1 | 两套前端并存 | MEDIUM | 架构 | static/index.html vs frontend/ 功能不一致 |
| M2 | SSE 用 GET 方法 | MEDIUM | API 设计 | URL 长度限制 |
| M3 | WS URL 硬编码 localhost | MEDIUM | 部署 | 服务器环境不工作 |
| M4 | 重连无用户提示 | MEDIUM | 前端 | 静默重试 |
| M5 | 移动端 sidebar 消失丢状态 | MEDIUM | 响应式 | |
| M6 | React typing dots 无动画 | MEDIUM | 视觉 | `ant-typing-dot` 无 CSS |

---

## Round 1 Action Plan

### 自主修复

- [ ] **C2/C3**: 修复实体提取 — strategy 层从用户消息中提取关键字段
- [ ] **H3**: 友好化错误信息
- [ ] **H5**: Mock 数据中文化
- [ ] **M2**: SSE 改为 POST
- [ ] **M3**: WebSocket URL 动态获取
- [ ] **M6**: 添加 typing 动画 CSS

### 记录不修改（需要产品/架构决策）

- **C1**: confidence 评分逻辑重设计
- **H1**: 欢迎引导需要产品定义
- **H2**: REST 上下文追踪需架构变更
- **H4/H5/M1**: 前端统一化决策
