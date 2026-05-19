# 部署与成本治理设计

> 依赖契约：无直接接口依赖（基础设施层）

---

## 1. 开发环境（Docker Compose）

```yaml
services:
  agent-api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [redis, postgres, milvus]

  postgres:
    image: postgres:16-alpine
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: open_chat_shop
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-devpassword}

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  milvus:
    image: milvusdb/milvus:v2.4-latest
    ports: ["19530:19530"]

  elasticsearch:
    image: elasticsearch:8.12.0
    ports: ["9200:9200"]
    environment:
      discovery.type: single-node
      xpack.security.enabled: "false"
    profiles: ["full"]

  admin-ui:
    build: ./sdk/web
    ports: ["3000:3000"]
```

## 2. 生产部署（Kubernetes）

```bash
helm install open-chat-shop ./helm \
  --set provider.type=anthropic \
  --set provider.model=claude-sonnet-4-6 \
  --set redis.cluster.enabled=true \
  --set milvus.mode=cluster
```

## 3. 私有化部署

```yaml
provider:
  type: ollama
  model: qwen2.5:14b
  embedding:
    type: ollama
    model: bge-m3

storage:
  vector: chromadb
  session: redis
  knowledge: sqlite
```

## 4. Token 成本模型

```yaml
cost_model:
  per_session_budget:
    max_tokens: 50_000
    warning_threshold: 40_000
    hard_stop: true

  strategy:
    cascade_savings:
      level_1_cost: 0
      level_2_cost: "~$0.002/query"
      level_3_cost: "~$0.01/query"
      estimated_distribution: "80% / 15% / 5%"

    context_compression:
      enabled: true
      target_compression_ratio: 0.6
      trigger_threshold: 0.8

    tool_injection_limit:
      max_tools_per_turn: 8
```

## 5. 成本监控

```yaml
cost_monitoring:
  metrics:
    - tokens_per_session
    - tokens_per_intent
    - llm_call_distribution
    - cost_per_resolved_case
    - cost_per_channel

  alerting:
    - condition: "daily_cost > budget * 0.8"
      action: notify_admin
    - condition: "single_session_cost > threshold"
      action: force_context_compression
    - condition: "level_3_ratio > 20%"
      action: review_intent_model
```

## 6. 预估成本参考

| 场景 | 日对话量 | 级联分布 | 预估月成本 |
|------|---------|---------|-----------|
| 小型电商 | 500 次 | 80/15/5 | $30-50 |
| 中型电商 | 5,000 次 | 80/15/5 | $200-400 |
| 大型电商 | 50,000 次 | 85/10/5 | $1,500-3,000 |

> 使用本地模型（Ollama）可将成本降至接近零（仅硬件成本）。

## 7. 可观测性

| 组件 | 用途 |
|------|------|
| OpenTelemetry | 链路追踪 |
| Prometheus | 指标采集 |
| Grafana | 仪表盘（含成本看板） |
| 结构化日志 | JSON 格式，ELK 检索 |
