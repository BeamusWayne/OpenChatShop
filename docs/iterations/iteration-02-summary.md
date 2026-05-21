# Iteration 2 总结: 内存泄漏修复

**日期**: 2026-05-21 | **迭代**: 2/15 | **状态**: 完成

## 修改内容

1. core/context.py: InMemoryContextManager 添加 TTL 1800s，过期自动驱逐
2. core/orchestrator.py: _session_locks LRU cap 10000，超限时批量清理
3. api/app.py: WS 断开清理 _session_modes；后台清理协程每 30 分钟清理 stale 数据

## 测试结果

17/17 通过（test_context.py + test_orchestrator.py）。无新失败。

## 下一步: Iteration 3 WebSocket 重连 + 心跳
