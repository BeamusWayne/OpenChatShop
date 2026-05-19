# Provider 抽象层设计

> 依赖契约：[contracts.md](./contracts.md) §2 — LLMProvider 接口及相关数据结构

---

## 1. 设计原则

1. **接口最小化** — 只定义 `chat`、`stream`、`embed` 三个核心方法
2. **能力声明** — 每个 Provider 声明自身能力，上层按能力降级
3. **配置驱动** — 通过 YAML 配置切换 Provider，无需改代码
4. **热切换** — 支持运行时切换 Provider（A/B 测试、灰度发布）

## 2. 内置 Provider 清单

| Provider | 说明 | 适用场景 |
|----------|------|---------|
| `OpenAIProvider` | GPT-4o / GPT-4.1 系列 | 通用高质量对话 |
| `AnthropicProvider` | Claude Sonnet / Opus | 复杂推理、长上下文 |
| `QwenProvider` | 通义千问系列 | 国内部署、中文优化 |
| `DeepSeekProvider` | DeepSeek V3 / R1 | 高性价比推理 |
| `OllamaProvider` | 本地部署模型 | 私有化、数据敏感场景 |
| `LiteLLMProvider` | 通过 LiteLLM 代理 100+ 模型 | 快速适配新模型 |

## 3. 级联策略

三级级联，按成本和精度递进：

| 级别 | 方式 | 延迟 | 成本 | 兜底 |
|------|------|------|------|------|
| Level 1 | 规则 + 语义检索 | P99 < 50ms | 零 | → Level 2 |
| Level 2 | 通用 LLM | P99 < 1s | ~$0.002/query | → Level 3 |
| Level 3 | 高精度 / 领域微调 LLM | P99 < 3s | ~$0.01/query | → 人工 |

```yaml
cascade:
  - level: 1
    type: rule_and_embedding
    confidence_threshold: 0.85
    fallback: level_2

  - level: 2
    provider: configurable
    model: configurable
    temperature: 0.3
    fallback: level_3

  - level: 3
    provider: configurable
    model: configurable
    temperature: 0.1
    fallback: human_handoff
```

## 4. 配置规范

```yaml
providers:
  primary:
    type: anthropic
    model: claude-sonnet-4-6
    api_key: ${ANTHROPIC_API_KEY}
    max_tokens: 4096
    timeout: 30

  fallback:
    type: openai
    model: gpt-4.1
    api_key: ${OPENAI_API_KEY}

  embedding:
    type: openai
    model: text-embedding-3-small

  local:
    type: ollama
    model: qwen2.5:14b
    base_url: http://localhost:11434

cascade:
  intent_classification:
    - provider: local
      confidence: 0.9
    - provider: primary

  dialogue_generation:
    - provider: primary
    - provider: fallback
```

## 5. 能力降级策略

当 Provider 不支持某能力时，系统自动降级：

| 场景 | 降级行为 |
|------|---------|
| Provider 不支持 `tool_calling` | 由编排器解析 LLM 文本输出，提取工具调用意图 |
| Provider 不支持 `streaming` | 使用 `chat()` 同步返回，前端等待完整响应 |
| Provider 不支持 `vision` | 拒绝图片输入，提示用户用文字描述 |
| 上下文超出 `max_context_tokens` | 触发上下文压缩（见 [context-manager.md](./context-manager.md)） |
| Provider API 超时 | 自动切换到 fallback Provider |
