import { useState, useRef, useEffect } from 'react';
import { Input, Button, Divider, Typography, Tag, theme } from 'antd';
import { SendOutlined, RobotOutlined } from '@ant-design/icons';
import type { ChatMessage } from '../types/agent';
import ProductGrid from './rich/ProductGrid';
import OrderCard from './rich/OrderCard';
import LogisticsTimeline from './rich/LogisticsTimeline';
import TransferStatus from './rich/TransferStatus';

interface AgentChatProps {
  sessionId: string;
  messages: ChatMessage[];
  onSendMessage: (content: string) => void;
}

export default function AgentChat({ messages, onSendMessage }: AgentChatProps) {
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { token } = theme.useToken();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    if (!inputValue.trim()) return;
    onSendMessage(inputValue.trim());
    setInputValue('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Separate AI (pre-transfer) messages from live agent/customer messages
  const aiMessages = messages.filter((m) => m.messageType === 'ai_summary' || m.role === 'system');
  const liveMessages = messages.filter(
    (m) => m.messageType !== 'ai_summary' && m.role !== 'system',
  );

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Messages Area */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 24px' }}>
        {/* AI Conversation Summary */}
        {aiMessages.length > 0 && (
          <>
            <Divider style={{ fontSize: 12, color: token.colorTextTertiary }}>
              <RobotOutlined style={{ marginRight: 6 }} />
              AI 对话记录
            </Divider>
            {aiMessages.map((msg) => (
              <div key={msg.id} style={{ marginBottom: 12 }}>
                <div
                  style={{
                    background: '#f6f4f0',
                    borderRadius: 8,
                    padding: '8px 12px',
                    fontSize: 13,
                    color: token.colorTextSecondary,
                  }}
                >
                  {msg.content}
                </div>
              </div>
            ))}
            <Divider plain>
              <Tag>人工服务开始</Tag>
            </Divider>
          </>
        )}

        {/* Live Messages */}
        {liveMessages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {messages.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: token.colorTextQuaternary }}>
            <Typography.Text type="secondary">会话已建立，等待消息...</Typography.Text>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div
        style={{
          borderTop: `1px solid ${token.colorBorderSecondary}`,
          padding: '12px 24px',
          display: 'flex',
          gap: 8,
          alignItems: 'flex-end',
          background: '#fff',
        }}
      >
        <Input.TextArea
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入消息... (Enter 发送)"
          autoSize={{ minRows: 1, maxRows: 4 }}
          style={{ flex: 1, borderRadius: 8 }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={handleSend}
          disabled={!inputValue.trim()}
        >
          发送
        </Button>
      </div>
    </div>
  );
}

interface MessageBubbleProps {
  message: ChatMessage;
}

function MessageBubble({ message }: MessageBubbleProps) {
  const { token } = theme.useToken();
  const isAgent = message.role === 'agent';

  const renderRichContent = (): React.ReactNode => {
    switch (message.messageType) {
      case 'product_search':
        return <ProductGrid payload={message.payload ?? {}} />;
      case 'order_detail':
        return <OrderCard payload={message.payload ?? {}} />;
      case 'logistics':
        return <LogisticsTimeline payload={message.payload ?? {}} />;
      case 'transfer_status':
        return <TransferStatus payload={message.payload ?? {}} />;
      default:
        return null;
    }
  };

  const richContent = renderRichContent();

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isAgent ? 'flex-end' : 'flex-start',
        marginBottom: 12,
      }}
    >
      <div style={{ maxWidth: '70%' }}>
        {message.content && (
          <div
            style={{
              background: isAgent ? '#ff5600' : token.colorBgLayout,
              color: isAgent ? '#fff' : token.colorText,
              borderRadius: isAgent ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
              padding: '8px 14px',
              fontSize: 14,
              lineHeight: 1.5,
              wordBreak: 'break-word',
            }}
          >
            {message.content}
          </div>
        )}
        {richContent && (
          <div style={{ marginTop: message.content ? 8 : 0 }}>{richContent}</div>
        )}
        <div
          style={{
            fontSize: 11,
            color: token.colorTextQuaternary,
            marginTop: 4,
            textAlign: isAgent ? 'right' : 'left',
          }}
        >
          {new Date(message.timestamp).toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </div>
      </div>
    </div>
  );
}
