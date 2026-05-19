import { useState, useRef, useEffect } from 'react';
import { Input, Button, Badge, Space } from 'antd';
import { SendOutlined, ClearOutlined } from '@ant-design/icons';
import { createStyles } from 'antd-style';
import { useChat } from '../hooks/useChat';
import MessageBubble from './MessageBubble';

const useStyles = createStyles(({ css, token }) => ({
  container: css({
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    maxHeight: '100vh',
    background: 'linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%)',
    color: token.colorText,
    overflow: 'hidden',
  }),
  header: css({
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '16px 24px',
    background: 'rgba(255, 255, 255, 0.05)',
    backdropFilter: 'blur(12px)',
    borderBottom: '1px solid rgba(255, 255, 255, 0.1)',
  }),
  title: css({
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    margin: 0,
    fontSize: 20,
    fontWeight: 600,
    color: '#fff',
  }),
  logo: css({
    width: 40,
    height: 40,
    borderRadius: 12,
    background: 'linear-gradient(135deg, #8b5cf6, #6366f1)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 20,
  }),
  messagesArea: css({
    flex: 1,
    overflow: 'auto',
    padding: '20px 24px',
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
    '&::-webkit-scrollbar': { width: 6 },
    '&::-webkit-scrollbar-track': { background: 'transparent' },
    '&::-webkit-scrollbar-thumb': { background: 'rgba(255,255,255,0.2)', borderRadius: 3 },
  }),
  typingIndicator: css({
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    color: 'rgba(255,255,255,0.5)',
    fontSize: 13,
    padding: '4px 0',
  }),
  dot: css({
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: 'rgba(255,255,255,0.4)',
    animation: 'bounce 1.4s infinite ease-in-out both',
    '&:nth-child(1)': { animationDelay: '-0.32s' },
    '&:nth-child(2)': { animationDelay: '-0.16s' },
    '@keyframes bounce': {
      '0%, 80%, 100%': { transform: 'scale(0)' },
      '40%': { transform: 'scale(1)' },
    },
  }),
  inputArea: css({
    padding: '16px 24px',
    background: 'rgba(255, 255, 255, 0.05)',
    backdropFilter: 'blur(12px)',
    borderTop: '1px solid rgba(255, 255, 255, 0.1)',
  }),
  inputRow: css({ display: 'flex', gap: 8, alignItems: 'center' }),
  quickActions: css({ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }),
  quickBtn: css({
    background: 'rgba(255,255,255,0.08) !important',
    borderColor: 'rgba(255,255,255,0.15) !important',
    color: 'rgba(255,255,255,0.7) !important',
    backdropFilter: 'blur(4px)',
    '&:hover': {
      background: 'rgba(255,255,255,0.15) !important',
      color: '#fff !important',
    },
  }),
}));

const QUICK_ACTIONS = [
  { label: '查询订单', text: '查订单' },
  { label: '搜索商品', text: '搜索手机' },
  { label: '物流查询', text: '物流查询' },
  { label: '申请退款', text: '我要退款' },
  { label: '转人工', text: '转人工客服' },
];

export default function ChatWindow() {
  const { styles } = useStyles();
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
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.title}>
          <div className={styles.logo}>🛍</div>
          <span>CommerceAgent</span>
        </div>
        <Space>
          <Badge
            status={connection.connected ? 'success' : 'error'}
            text={
              <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: 13 }}>
                {connection.connected ? '已连接' : connection.reconnecting ? '重连中...' : '未连接'}
              </span>
            }
          />
          <Button
            type="text"
            icon={<ClearOutlined />}
            onClick={clearMessages}
            style={{ color: 'rgba(255,255,255,0.5)' }}
          />
        </Space>
      </div>

      <div className={styles.messagesArea}>
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} onSuggestionClick={sendMessage} />
        ))}
        {isTyping && (
          <div className={styles.typingIndicator}>
            <span className={styles.dot} />
            <span className={styles.dot} />
            <span className={styles.dot} />
            <span>正在思考...</span>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className={styles.inputArea}>
        <div className={styles.quickActions}>
          {QUICK_ACTIONS.map((a) => (
            <Button key={a.label} size="small" className={styles.quickBtn} onClick={() => sendMessage(a.text)}>
              {a.label}
            </Button>
          ))}
        </div>
        <div className={styles.inputRow}>
          <Input
            size="large"
            placeholder="输入消息..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={handleSend}
            disabled={!connection.connected}
            suffix={
              <Button
                type="text"
                icon={<SendOutlined />}
                onClick={handleSend}
                disabled={!input.trim() || !connection.connected}
              />
            }
          />
        </div>
      </div>
    </div>
  );
}
