import { useState, useRef, useEffect } from 'react';
import { Input, Button, Badge, Space, theme } from 'antd';
import { SendOutlined, ClearOutlined, RobotOutlined } from '@ant-design/icons';
import { useChat } from '../hooks/useChat';
import MessageBubble from './MessageBubble';

const QUICK_ACTIONS = [
  { label: '查询订单', text: '查订单' },
  { label: '搜索商品', text: '搜索手机' },
  { label: '物流查询', text: '物流查询' },
  { label: '申请退款', text: '我要退款' },
  { label: '转人工', text: '转人工客服' },
];

export default function ChatWindow() {
  const { token } = theme.useToken();
  const { messages, connection, isTyping, sendMessage, clearMessages } = useChat();
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
          padding: '16px 24px',
          background: token.colorBgContainer,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: token.borderRadiusLG,
              background: token.colorPrimary,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontSize: 20,
            }}
          >
            <RobotOutlined />
          </div>
          <span style={{ fontSize: 20, fontWeight: 600, color: token.colorText }}>
            CommerceAgent
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

      {/* Messages */}
      <div
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '20px 24px',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} onSuggestionClick={sendMessage} />
        ))}
        {isTyping && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: token.colorTextSecondary, fontSize: 13 }}>
            <span className="ant-typing-dot" />
            <span className="ant-typing-dot" />
            <span className="ant-typing-dot" />
            <span>正在思考...</span>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div
        style={{
          padding: '16px 24px',
          background: token.colorBgContainer,
          borderTop: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        <Space size={[8, 8]} wrap style={{ marginBottom: 10 }}>
          {QUICK_ACTIONS.map((a) => (
            <Button key={a.label} size="small" onClick={() => sendMessage(a.text)}>
              {a.label}
            </Button>
          ))}
        </Space>
        <div style={{ display: 'flex', gap: 8 }}>
          <Input
            size="large"
            placeholder="输入消息..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={handleSend}
            disabled={!connection.connected}
          />
          <Button
            type="primary"
            size="large"
            icon={<SendOutlined />}
            onClick={handleSend}
            disabled={!input.trim() || !connection.connected}
          />
        </div>
      </div>
    </div>
  );
}
