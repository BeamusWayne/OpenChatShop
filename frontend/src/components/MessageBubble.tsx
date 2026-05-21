import { Typography, Space, Tag, theme } from 'antd';
import { RobotOutlined, UserOutlined, CustomerServiceOutlined } from '@ant-design/icons';
import type { ChatMessage } from '../types/chat';
import OrderCard from './rich/OrderCard';
import LogisticsTimeline from './rich/LogisticsTimeline';
import ProductGrid from './rich/ProductGrid';
import TransferStatus from './rich/TransferStatus';

const AI_ACCENT = '#ff5600';
const AI_ACCENT_BG = '#fff5eb';
const AGENT_COLOR = '#1677ff';
const AGENT_BG = '#e6f4ff';

interface Props {
  message: ChatMessage;
  onSuggestionClick?: (text: string) => void;
}

export default function MessageBubble({ message, onSuggestionClick }: Props) {
  const { token } = theme.useToken();

  const isUser = message.role === 'user';
  const isAgent = message.role === 'agent';
  const isAssistant = message.role === 'assistant';
  const isSystem = message.role === 'system';
  const isFromBot = isAssistant;

  const timeStr = message.timestamp
    ? new Date(message.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : '';

  return (
    <div
      style={{
        display: 'flex',
        gap: 8,
        maxWidth: isSystem ? '95%' : '75%',
        alignSelf: isUser ? 'flex-end' : 'flex-start',
        flexDirection: isUser ? 'row-reverse' : 'row',
      }}
    >
      {!isSystem && (
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            fontSize: 16,
            background: isUser ? token.colorPrimary : isAgent ? AGENT_BG : AI_ACCENT_BG,
            color: isUser ? '#fff' : isAgent ? AGENT_COLOR : AI_ACCENT,
          }}
        >
          {isUser ? <UserOutlined /> : isAgent ? <CustomerServiceOutlined /> : <RobotOutlined />}
        </div>
      )}
      <div>
        {isAgent && message.agentName && (
          <div style={{ fontSize: 12, color: AGENT_COLOR, marginBottom: 2, marginLeft: 4 }}>
            客服 {message.agentName}
          </div>
        )}
        <div
          style={{
            padding: '10px 14px',
            borderRadius: token.borderRadius,
            ...(isUser
              ? {
                  background: token.colorPrimary,
                  color: token.colorTextLightSolid,
                  borderTopRightRadius: token.borderRadiusXS,
                }
              : isAgent
                ? {
                    background: AGENT_BG,
                    border: `1px solid #bae0ff`,
                    borderTopLeftRadius: token.borderRadiusXS,
                  }
                : isAssistant
                  ? {
                      background: token.colorBgContainer,
                      border: `1px solid ${token.colorBorderSecondary}`,
                      borderTopLeftRadius: token.borderRadiusXS,
                    }
                  : {
                      background: '#e8f4fd',
                      borderRadius: token.borderRadius,
                      fontSize: 13,
                      color: token.colorTextSecondary,
                    }),
            lineHeight: 1.6,
            wordBreak: 'break-word',
            whiteSpace: 'pre-wrap',
          }}
        >
          <Typography.Text style={{ color: 'inherit' }}>
            {isFromBot && message.messageType === 'order_card' && message.payload ? (
              <OrderCard payload={message.payload as Parameters<typeof OrderCard>[0]['payload']} />
            ) : isFromBot && message.messageType === 'logistics_timeline' && message.payload ? (
              <LogisticsTimeline payload={message.payload as Parameters<typeof LogisticsTimeline>[0]['payload']} />
            ) : isFromBot && message.messageType === 'product_list' && message.payload ? (
              <ProductGrid payload={message.payload as Parameters<typeof ProductGrid>[0]['payload']} />
            ) : message.messageType === 'transfer' && message.payload ? (
              <TransferStatus payload={message.payload as Parameters<typeof TransferStatus>[0]['payload']} />
            ) : (
              message.content
            )}
          </Typography.Text>
        </div>
        {isFromBot && message.suggestions && message.suggestions.length > 0 && (
          <Space size={[6, 6]} wrap style={{ marginTop: 6 }}>
            {message.suggestions.map((s) => (
              <Tag key={s} style={{ cursor: 'pointer' }} onClick={() => onSuggestionClick?.(s)}>
                {s}
              </Tag>
            ))}
          </Space>
        )}
        {timeStr && (
          <div
            style={{
              fontSize: 11,
              color: token.colorTextQuaternary,
              marginTop: 4,
              textAlign: isUser ? 'right' : 'left',
              paddingRight: isUser ? 4 : 0,
              paddingLeft: isUser ? 0 : 4,
            }}
          >
            {timeStr}
          </div>
        )}
      </div>
    </div>
  );
}
