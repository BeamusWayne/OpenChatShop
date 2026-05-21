# Iteration 2: 内存泄漏修复

session/socket dicts unbounded; InMemoryContextManager no TTL.

## Changes
- api/app.py: WS disconnect clears _session_messages; background cleanup coroutine
- core/context.py: InMemoryContextManager TTL 1800s
- core/orchestrator.py: _session_locks LRU cap 10000
