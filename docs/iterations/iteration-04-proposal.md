# Iteration 4: 消息持久化

## 问题
刷新页面丢失全部对话历史。

## 修改
- useChat.ts: 消息自动存 sessionStorage（按 session_id）, 页面加载恢复历史（最多 200 条）, 新会话清理旧数据
