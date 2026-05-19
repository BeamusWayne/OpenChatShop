# 工具系统设计

> 依赖契约：[contracts.md](./contracts.md) §3 — BaseTool 接口、§4 — ToolInjector 接口

---

## 1. 模块职责

注册、发现、注入和执行工具。核心原则：工具按意图动态注入，不静态全量加载。

## 2. 意图驱动动态注入

工具注入经过四层过滤：

1. **意图匹配** — 根据意图名从注册表查找候选工具集
2. **场景过滤** — 当前业务场景 FSM 只暴露相关工具（如退款场景不暴露商品推荐）
3. **权限过滤** — 根据用户角色过滤（如 customer 不能调用 agent-only 工具）
4. **数量截断** — 最多注入 8 个工具，避免上下文膨胀

注入时机：在 DialogueOrchestrator 主流程第 4 步，意图识别之后、策略决策之前。

## 3. 工具注册元数据

```yaml
tool: query_order
description: 查询订单详情
category: order
permissions:
  required_roles: [customer, agent]
  sensitive_output: true
  idempotent: true
  estimated_latency_ms: 200
validation:
  params_schema:
    type: object
    required: [order_id]
    properties:
      order_id:
        type: string
        pattern: "^ORD-[0-9-]+$"
  pre_conditions:
    - order_belongs_to_user
retry:
  max_attempts: 2
  backoff: exponential
compensation:
  type: none
```

## 4. 动态路由

意图到工具的映射配置：

```yaml
routing:
  - intent: ["查询订单", "订单状态"]
    tools: [query_order, query_logistics]
    priority: [query_order]

  - intent: ["退款", "退货"]
    tools: [check_refund_eligibility, create_refund, query_refund]
    requires_confirmation: true
    compensation: cancel_refund
```

## 5. 安全矩阵

| 操作类型 | 客户自助 | 需确认 | 需人工审批 |
|---------|---------|--------|-----------|
| 查询订单 | Y | - | - |
| 修改地址 | - | Y 二次确认 | - |
| 发起退款 | - | Y 金额确认 | 金额 > 500 |
| 取消订单 | - | Y | 已发货状态 |
| 修改价格 | - | - | Y 坐席权限 |

## 6. 执行流程

```
LLM 输出 ToolCall → 参数校验(JSON Schema) → 前置校验(pre_check)
  → 权限检查(RBAC) → 确认弹窗(如需) → execute() → 结果脱敏 → 返回
  ↓ 失败
  重试(max_attempts) → 仍失败 → 补偿(compensate) → 错误回复用户
```

## 7. 内置电商工具集

| 工具 | 类别 | 读写 | 描述 |
|------|------|------|------|
| query_order | order | 读 | 查询订单详情 |
| query_logistics | logistics | 读 | 查询物流状态 |
| search_product | product | 读 | 商品搜索/推荐 |
| check_refund_eligibility | refund | 读 | 检查退款资格 |
| create_refund | refund | 写 | 创建退款申请 |
| cancel_order | order | 写 | 取消订单 |
| modify_address | order | 写 | 修改收货地址 |
| handoff_to_human | handoff | 写 | 转接人工坐席 |
```
