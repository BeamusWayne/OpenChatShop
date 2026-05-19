# 意图识别引擎设计

> 依赖契约：[contracts.md](./contracts.md) §1.4 — Intent 数据结构、§2 — LLMProvider 接口

---

## 1. 模块职责

将用户输入分类为结构化意图。采用三级级联架构，兼顾成本、延迟和精度。

## 2. 三级级联架构

```
用户输入
  │
  ▼
Level 1: 规则 + 语义检索
  │ confidence >= 0.85? → 返回
  ▼
Level 2: 通用 LLM
  │ confidence >= 0.7? → 返回
  ▼
Level 3: 高精度 LLM
  │ confidence >= 0.5? → 返回
  ▼
人工转接
```

## 3. Level 1：规则 + 语义检索

### 3.1 规则匹配

```yaml
rules:
  - patterns: ["订单", "物流", "快递", "发货"]
    intent: query_order
    confidence: 0.9

  - patterns: ["退款", "退货", "退钱"]
    intent: request_refund
    confidence: 0.9

  - patterns: ["人工", "客服", "转接"]
    intent: handoff_human
    confidence: 0.95
```

优先级：精确匹配 > 正则匹配 > 关键词包含。

### 3.2 语义检索

将用户输入向量化，在意图样本库中检索最近邻。

```yaml
semantic_search:
  vector_store: intent_examples  # 见 data-architecture.md
  top_k: 3
  similarity_threshold: 0.85
  fallback: level_2
```

## 4. Level 2：通用 LLM

使用成本较低的 LLM 做意图分类，附带实体提取：

```yaml
level_2:
  provider: configurable
  model: configurable
  temperature: 0.1  # 低温度，追求确定性
  system_prompt: |
    你是电商客服意图分类器。将用户输入分类为以下意图之一：
    {intent_list}

    输出 JSON: {"intent": "...", "confidence": 0.0-1.0, "entities": {...}}
  max_tokens: 200
```

## 5. Level 3：高精度 LLM

用于复杂/模糊输入，使用更强的模型：

```yaml
level_3:
  provider: configurable
  model: configurable
  temperature: 0.0
  system_prompt: |
    你是资深电商客服意图分析专家。用户输入可能模糊、口语化或包含错别字。
    结合上下文历史分析真实意图。

    输出 JSON: {"intent": "...", "confidence": 0.0-1.0, "entities": {...}, "reasoning": "..."}
  max_tokens: 500
```

## 6. 上下文辅助

意图识别不只看当前输入，还参考上下文：

- 当前 FSM 状态 → 缩小候选意图范围
- 槽位中的实体 → 辅助消歧（如"退货"结合 complaint_type="quality"）
- 最近 3 轮对话 → 理解省略主语的输入

## 7. 置信度阈值配置

```yaml
thresholds:
  high_confidence: 0.85      # 直接执行
  medium_confidence: 0.7     # 执行但准备 fallback
  low_confidence: 0.5        # 确认意图后再执行
  very_low_confidence: 0.3   # 建议转人工
```

## 8. 意图样本库管理

```yaml
intent_samples:
  per_intent_min: 20         # 每个意图最少 20 个标注样本
  total_target: 500+         # 总样本数
  update_frequency: weekly   # 每周从线上对话中筛选新增样本
  review_process: human_in_loop  # 新样本需人工确认后入库
```
