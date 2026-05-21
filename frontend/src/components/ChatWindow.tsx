import { useState, useRef, useEffect } from 'react';
import { Input, Button, Badge, Space, Spin, theme } from 'antd';
import { SendOutlined, ClearOutlined, RobotOutlined, CustomerServiceOutlined } from '@ant-design/icons';
import { useChat } from '../hooks/useChat';
import MessageBubble from './MessageBubble';
import WelcomeScreen from './WelcomeScreen';
import type { SessionMode } from '../types/chat';

const AI_QUICK_ACTIONS = [
  { label: '查询订单', text: '查订单' },
  { label: '搜索商品', text: '搜索手机' },
  { label: '物流查询', text: '物流查询' },
  { label: '申请退款', text: '我要退款' },
];

const AI_ACCENT = '#ff5600';
const AI_ACCENT_BG = '#fff5eb';
const AGENT_COLOR = '#1677ff';
const AGENT_BG = '#e6f4ff';

function getHeaderConfig(mode: SessionMode) {
  switch (mode) {
    case 'human_mode':
      return {
        icon: <CustomerServiceOutlined />,
        iconBg: AGENT_BG,
        iconColor: AGENT_COLOR,
        title: '人工客服',
      };
    case 'transfer_pending':
      return {
        icon: <CustomerServiceOutlined />,
        iconBg: '#fff7e6',
        iconColor: '#fa8c16',
        title: '正在转接...',
      };
    default:
      return {
        icon: <RobotOutlined />,
        iconBg: AI_ACCENT_BG,
        iconColor: AI_ACCENT,
        title: 'OpenChatShop',
      };
  }
}

function getDateLabel(ts: number): string {
  const msgDate = new Date(ts);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const msgDay = new Date(msgDate.getFullYear(), msgDate.getMonth(), msgDate.getDate());
  if (msgDay.getTime() === today.getTime()) return '今天';
  if (msgDay.getTime() === yesterday.getTime()) return '昨天';
  return msgDate.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' });
}

export default function ChatWindow() {
  const { token } = theme.useToken();
  const { messages, connection, isTyping, sessionMode, sendMessage, clearMessages } = useChat();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const handleSend = () => {
    if (!input.trim()) return;
    sendMessage(input);
    setInput('');
  };

  const isHumanMode = sessionMode === 'human_mode';
  const isTransferPending = sessionMode === 'transfer_pending';
  const hasUserMessages = messages.some((m) => m.role === 'user');

  const headerConfig = getHeaderConfig(sessionMode);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        maxHeight: '100vh',
        background: token.colorBgLayout,
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: `${token.padding}px ${token.paddingLG}px`,
          background: token.colorBgContainer,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: token.paddingXS }}>
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: token.borderRadiusLG,
              background: headerConfig.iconBg,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: headerConfig.iconColor,
              fontSize: 20,
            }}
          >
            {headerConfig.icon}
          </div>
          <span style={{ fontSize: 20, fontWeight: 600, color: headerConfig.iconColor, letterSpacing: -0.3 }}>
            {headerConfig.title}
          </span>
        </div>
        <Space>
          <Badge
            status={connection.connected ? 'success' : 'error'}
            text={
              <span style={{ color: token.colorTextSecondary, fontSize: 13 }}>
                {connection.connected ? '已连接' : connection.reconnecting ? '重连中...' : '未连接'}
              </span>
            }
          />
          <Button type="text" icon={<ClearOutlined />} onClick={clearMessages} />
        </Space>
      </div>

      {/* Messages / Welcome */}
      {!hasUserMessages ? (
        <WelcomeScreen onAction={sendMessage} />
      ) : (
        <div
          style={{
            flex: 1,
            overflow: 'auto',
            padding: `20px ${token.paddingLG}px`,
            display: 'flex',
            flexDirection: 'column',
            gap: token.padding,
          }}
        >
          {messages.map((msg, i) => {
            const showDateSep = i === 0 || (
              msg.timestamp &&
              messages[i - 1].timestamp &&
              new Date(msg.timestamp).toDateString() !== new Date(messages[i - 1].timestamp).toDateString()
            );
            return (
              <div key={msg.id}>
                {showDateSep && msg.timestamp && (
                  <div style={{ textAlign: 'center', margin: '8px 0', fontSize: 12, color: token.colorTextQuaternary }}>
                    {getDateLabel(msg.timestamp)}
                  </div>
                )}
                <MessageBubble message={msg} onSuggestionClick={sendMessage} />
              </div>
            );
          })}
          {isTyping && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: token.colorTextSecondary, fontSize: 13 }}>
              <Spin size="small" />
              <span>{isHumanMode ? '客服正在输入...' : '正在思考...'}</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      )}

      {/* Input area */}
      <div
        style={{
          padding: `${token.padding}px ${token.paddingLG}px`,
          paddingBottom: `max(${token.padding}px, env(safe-area-inset-bottom, 0px))`,
          background: token.colorBgContainer,
          borderTop: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        {!isHumanMode && !isTransferPending && (
          <Space size={[8, 8]} wrap style={{ marginBottom: 10 }}>
            {AI_QUICK_ACTIONS.map((a) => (
              <Button key={a.label} size="small" onClick={() => sendMessage(a.text)}>
                {a.label}
              </Button>
            ))}
            <Button size="small" type="link" onClick={() => sendMessage('转人工客服')}>
              转人工客服
            </Button>
          </Space>
        )}
        <div style={{ display: 'flex', gap: 8 }}>
          <Input
            size="large"
            placeholder={
              isHumanMode ? '发送给客服...'
              : isTransferPending ? '正在转接，请稍候...'
              : '输入消息...'
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={handleSend}
            disabled={!connection.connected || isTransferPending}
          />
          <Button
            type={isHumanMode ? 'default' : 'primary'}
            size="large"
            icon={<SendOutlined />}
            onClick={handleSend}
            disabled={!input.trim() || !connection.connected || isTransferPending}
            style={isHumanMode ? { borderColor: AGENT_COLOR, color: AGENT_COLOR } : undefined}
          />
        </div>
      </div>
    </div>
  );
}
