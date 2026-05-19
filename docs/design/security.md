# 安全防护设计

> 依赖契约：[contracts.md](./contracts.md) §3 — ToolPermission、§1.5 — SessionContext

---

## 1. 安全架构

```
用户输入
  │
  ▼
Prompt 注入检测器（规则 + ML 双引擎）
  │ 通过
  ▼
内容安全过滤（敏感词 + PII 检测）
  │ 通过
  ▼
工具调用权限校验（RBAC + 场景约束）
  │ 通过
  ▼
输出脱敏 + 水印（手机号/地址/金额）
  │
安全响应
```

## 2. Prompt 注入检测

双引擎检测，任一引擎报警即拦截：

| 引擎 | 方式 | 覆盖场景 |
|------|------|---------|
| 规则引擎 | 正则 + 关键词匹配 | 已知攻击模式 |
| ML 引擎 | 轻量分类模型 | 变形攻击、编码绕过、间接注入 |

```yaml
injection_detection:
  rule_engine:
    patterns:
      - "ignore.*(previous|above|prior)"
      - "you are now"
      - "system:"
    action: block

  ml_engine:
    model: configurable
    threshold: 0.8
    action: block_and_log
```

## 3. 内容安全过滤

```yaml
content_filter:
  pii_detection:
    fields: [phone, email, id_card, bank_card]
    action: mask_and_warn

  sensitive_words:
    source: configurable_list
    action: block_or_warn

  output_filter:
    phone: "138****1234"
    address: "北京市****"
    id_card: "110***********1234"
    bank_card: "**** **** **** 5678"
```

## 4. 认证与授权

### 4.1 认证方式

| 方式 | 适用场景 | 优先级 |
|------|---------|--------|
| JWT Bearer Token | 已登录用户会话 | 1 |
| API Key | 服务间调用 / 开放 API | 2 |
| 微信 OAuth | 微信渠道自动鉴权 | 3 |

### 4.2 RBAC 模型

| 角色 | 权限范围 |
|------|---------|
| customer | 查询、自助操作 |
| agent | customer + 确认审批 |
| admin | 全部 + 配置管理 |
| system | 内部服务间调用 |

### 4.3 请求流程

```
Request → 认证中间件 → RBAC 校验 → 业务处理
                                    ↑
                          工具调用额外检查 ToolPermission
```

## 5. 审计日志

```yaml
audit:
  log_level: all_actions
  storage: postgresql (按周分区，保留 36 个月)
  fields:
    - timestamp
    - session_id
    - user_id
    - action_type       # "chat" | "tool_call" | "handoff" | "config_change"
    - tool_name
    - request_summary   # 脱敏后
    - response_summary
    - risk_score        # 0-100
  alerting:
    - condition: "risk_score > 80"
      action: notify_admin
```

## 6. 速率限制

见 [data-architecture.md](./data-architecture.md) §4 Redis rate_limit 配置。
