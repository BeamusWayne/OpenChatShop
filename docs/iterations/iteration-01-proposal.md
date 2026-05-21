# Iteration 1: API 输入校验 + 错误响应标准化

**日期**: 2026-05-21 | **迭代**: 1/15

## 问题诊断

1. ChatRequest.content 无长度限制 → 可发送多 MB 消息
2. session_id 无格式校验 → 可注入任意字符串
3. SSE 流式端点 Query 参数完全无校验
4. API 错误信息为开发者风格 → 直接暴露给用户
5. RegisterRequest.name 无长度限制

## 业界参考

淘宝/京东: 所有字段 max_length + 错误码分类
Shopify: 统一错误格式
标准: 422 用于校验失败

## 自主决策

所有修改均可自主决策。

## 修改清单

| 文件 | 修改 |
|------|------|
| api/app.py | ChatRequest 加 max_length |
| api/app.py | SSE Query 加 max_length |
| api/agent.py | RegisterRequest 加 max_length |
| api/auth.py | 401 中文友好提示 |
