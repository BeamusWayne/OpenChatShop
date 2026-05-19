# 数据架构设计

> 依赖契约：无直接接口依赖（基础设施层，被其他模块消费）

---

## 1. 三层存储架构

```
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│   向量存储      │  │   关系数据库    │  │   缓存集群      │
│  (知识/语义)    │  │  (业务数据)     │  │  (会话/热数据)  │
│  Milvus/PG/    │  │  PostgreSQL     │  │  Redis Cluster  │
│  ChromaDB      │  │                 │  │                 │
└────────────────┘  └────────────────┘  └────────────────┘
```

## 2. 向量数据库

### 2.1 存储选型（可插拔）

| 向量库 | 适用场景 | 索引类型 | 特点 |
|--------|---------|---------|------|
| Milvus | 大规模生产 | HNSW / IVF_PQ | 分布式、高性能 |
| pgvector | 中小规模 / 已有 PG | HNSW / IVFFlat | 零额外依赖 |
| ChromaDB | 开发测试 / 轻量部署 | HNSW | 嵌入式、零配置 |

### 2.2 索引策略

```yaml
vector_index:
  knowledge_base:
    dimension: configurable    # 取决于 Embedding 模型
    index_type: HNSW
    metric: cosine
    params:
      M: 16
      ef_construction: 256
    capacity: 500_000
    soft_delete: true
    tiering:
      hot: [7d, active_products]
      cold: [90d, archived]

  intent_examples:
    dimension: configurable
    index_type: HNSW
    metric: cosine
    capacity: 50_000
```

### 2.3 数据生命周期

```
写入 → 实时索引更新 → 定期 compaction → 冷热分离 → 归档/删除
              ↑
        软删除标记 → 异步重建索引
```

## 3. 关系数据库

### 3.1 分表策略

```yaml
relational_db:
  ticket_table:
    partition: range_by_month
    retention: 12_months
    archive_to: cold_storage

  user_profile:
    split:
      basic: [user_id, name, level, created_at]       # 低频更新
      behavior: [user_id, recent_views, preferences, last_active]  # 高频更新
    locking: optimistic

  audit_log:
    partition: range_by_week
    retention: 36_months
    index: [session_id, user_id, timestamp, action_type]
```

### 3.2 读写分离

```
写操作 → Primary DB (强一致性)
读操作 → Replica (最终一致性，延迟 < 100ms)
         ↓ 特殊场景
         Redis Cache (热点数据，延迟 < 5ms)
```

## 4. 缓存架构

```yaml
redis_cluster:
  session_store:
    structure: Hash
    ttl: 1800
    eviction: allkeys-lru

  hot_data:
    structure: Hash + Sorted Set
    use_cases:
      - user_basic_profile
      - product_realtime_info
      - order_status_cache
    ttl: 300
    update: cache_aside_pattern

  rate_limit:
    structure: Sorted Set (滑动窗口)
    limits:
      - key: "user:{id}:messages"
        window: 60s
        max: 30
      - key: "ip:{addr}:requests"
        window: 60s
        max: 60
      - key: "tool:{name}:calls"
        window: 3600s
        max: 1000
```

## 5. 数据同步

```
业务数据库 → Debezium CDC → Redis (热数据更新)
                            → 向量库 (知识库更新)
                            → Elasticsearch (搜索索引更新)
```
