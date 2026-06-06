# Iteration 3 提案: WebSocket 重连 + 心跳

## 问题
- useChat.ts 固定 3s 重连无退避
- 无心跳检测断线
- session_id 刷新后丢失
- 断线期间消息丢失

## 修改
- useChat.ts: 指数退避 (3s→60s), localStorage session 持久化, 心跳 30s/10s, 消息队列
- useAgent.ts: 指数退避 (3s→60s)
- static/index.html: 指数退避, localStorage session 持久化
- api/app.py: 心跳消息处理（已有）
