---
version: 1.0
name: OpenChatShop
description: >
  电商智能客服对话系统。基于 Intercom 风格适配——暖色调 canvas、
  charcoal 主色、单个 AI 橙色强调。设计目标：专业但不冰冷，
  适合 C 端消费者的电商客服场景。

colors:
  primary: "#111111"
  on-primary: "#ffffff"
  ai-accent: "#ff5600"
  canvas: "#f5f1ec"
  surface-1: "#ffffff"
  surface-2: "#ebe7e1"
  ink: "#111111"
  ink-muted: "#626260"
  ink-subtle: "#7b7b78"
  ink-tertiary: "#9c9fa5"
  hairline: "#d3cec6"
  hairline-soft: "#ebe7e1"
  success: "#0bdf50"
  error: "#c41c1c"
  warning: "#d4a017"
  info: "#65b5ff"

typography:
  display:
    fontFamily: "'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: 24px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.3px
  headline:
    fontFamily: "'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: -0.2px
  body:
    fontFamily: "'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: 0
  body-sm:
    fontFamily: "'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  caption:
    fontFamily: "'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: 0
  button:
    fontFamily: "'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: 15px
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: 0

rounded:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  pill: 9999px

spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px

components:
  chat-canvas:
    backgroundColor: "{colors.canvas}"
  chat-header:
    backgroundColor: "{colors.surface-1}"
    borderBottom: "1px solid {colors.hairline-soft}"
    padding: "{spacing.md} {spacing.lg}"
  chat-input-area:
    backgroundColor: "{colors.surface-1}"
    borderTop: "1px solid {colors.hairline-soft}"
    padding: "{spacing.md} {spacing.lg}"
  bubble-user:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    borderRadius: "{rounded.lg}"
    borderTopRight: "{rounded.xs}"
    padding: "10px 14px"
  bubble-assistant:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    border: "1px solid {colors.hairline}"
    borderRadius: "{rounded.lg}"
    borderTopLeft: "{rounded.xs}"
    padding: "10px 14px"
  bubble-system:
    backgroundColor: "#e8f4fd"
    textColor: "{colors.ink-muted}"
    borderRadius: "{rounded.lg}"
    fontSize: "{typography.body-sm.fontSize}"
    padding: "8px 14px"
  avatar-user:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    size: 36px
    borderRadius: "{rounded.pill}"
  avatar-bot:
    backgroundColor: "#fff5eb"
    textColor: "{colors.ai-accent}"
    size: 36px
    borderRadius: "{rounded.pill}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    borderRadius: "{rounded.md}"
    padding: "8px 16px"
  button-secondary:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    border: "1px solid {colors.hairline}"
    borderRadius: "{rounded.md}"
    padding: "8px 16px"
  button-ai:
    backgroundColor: "{colors.ai-accent}"
    textColor: "{colors.on-primary}"
    borderRadius: "{rounded.md}"
    padding: "8px 16px"
  suggestion-tag:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    border: "1px solid {colors.hairline}"
    borderRadius: "{rounded.md}"
    padding: "4px 12px"
  quick-action:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.ink}"
    border: "1px solid {colors.hairline}"
    borderRadius: "{rounded.md}"
    padding: "4px 12px"
---

## Overview

OpenChatShop 是一个面向电商 C 端消费者的智能客服系统。设计语言借鉴 Intercom 的 warm editorial 风格：

- **暖色 Canvas**（#f5f1ec）—— 不是纯白，传达亲切温度感
- **Charcoal 主色**（#111111）—— 专业、可靠，不依赖蓝/紫色
- **AI 橙色强调**（#ff5600）—— 仅用于 bot avatar 和 AI 视觉标识
- **白色浮动卡片**（#ffffff）—— 消息气泡、输入区、header 浮在 canvas 上
- **无阴影** —— 通过 canvas/surface 色差建立层级

## Token -> Ant Design 6 Mapping

| DESIGN.md Token | Ant Design Seed Token | Value |
|---|---|---|
| `{colors.primary}` | `colorPrimary` | `#111111` |
| `{colors.canvas}` | `colorBgLayout` | `#f5f1ec` |
| `{colors.surface-1}` | `colorBgContainer` | `#ffffff` |
| `{colors.ink}` | `colorText` | `#111111` |
| `{colors.ink-muted}` | `colorTextSecondary` | `#626260` |
| `{colors.ink-subtle}` | `colorTextTertiary` | `#7b7b78` |
| `{colors.hairline}` | `colorBorder` | `#d3cec6` |
| `{colors.hairline-soft}` | `colorBorderSecondary` | `#ebe7e1` |
| `{rounded.lg}` | `borderRadius` | `12` |
| Inter stack | `fontFamily` | `'Inter', system-ui, ...` |

## Colors

### Surface
- **Canvas** (#f5f1ec): 页面底色，聊天窗口背景
- **Surface-1** (#ffffff): Header、输入区、assistant 气泡
- **Surface-2** (#ebe7e1): hover 态或更深的分区背景

### Text
- **Ink** (#111111): 标题、正文、按钮
- **Ink Muted** (#626260): 连接状态、辅助信息
- **Ink Subtle** (#7b7b78): 时间戳、系统消息
- **Ink Tertiary** (#9c9fa5): disabled、footnotes

### Accent
- **AI Orange** (#ff5600): 仅用于 bot avatar 背景、AI 功能标记

## Typography

Inter 字体家族，靠 size + weight 区分层级。

| Role | Size | Weight | Use |
|---|---|---|---|
| Display | 24px | 600 | App 名称 |
| Headline | 20px | 600 | 区域标题 |
| Body | 16px | 400 | 消息正文、输入框 |
| Body-sm | 14px | 400 | 快捷操作、辅助文字 |
| Caption | 12px | 400 | 连接状态、时间戳 |

## Components

### Message Bubbles
- User: charcoal 背景 + 白字，右对齐，右上小圆角
- Assistant: 白背景 + hairline 边框，左对齐，左上小圆角
- System: 浅蓝背景，居中，小字号

### Avatar
36px 圆形。User: charcoal 底白字。Bot: 浅橙底 + AI Orange 图标。

### Suggestions
Canvas 底色 + hairline 边框的小 tag，点击触发发送。

### Quick Actions
输入区上方的 secondary button 组。

## Do's and Don'ts

### Do
- 用 canvas (#f5f1ec) 作为默认背景
- 用 white-on-canvas 色差建立层级
- AI Orange 只用于 bot 相关元素

### Don't
- 不要用纯白做 canvas 背景
- 不要用 drop shadow 建层级
- 不要把 AI Orange 作为通用主色
- 不要引入蓝/紫色作为品牌色
