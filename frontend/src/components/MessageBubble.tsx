import { Typography, Space, Tag, theme } from 'antd';
import { RobotOutlined, UserOutlined } from '@ant-design/icons';
import type { ChatMessage } from '../types/chat';
import OrderCard from './rich/OrderCard';
import LogisticsTimeline from './rich/LogisticsTimeline';
import ProductGrid from './rich/ProductGrid';
import TransferStatus from './rich/TransferStatus';

const AI_ACCENT = '#ff5600';
const AI_ACCENT_BG = '#fff5eb';

interface Props {
  message: ChatMessage;
  onSuggestionClick?: (text: string) => void;
}

export default function MessageBubble({ message, onSuggestionClick }: Props) {
  const { token } = theme.useToken();

  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const isSystem = message.role === 'system';

  return (
    <div
      style={{
        display: 'flex',
        gap: 8,
        maxWidth: isSystem ? '95%' : '75%',
        alignSelf: isUser ? 'flex-end' : isAssistant ? 'flex-start' : 'center',
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
            background: isUser ? token.colorPrimary : AI_ACCENT_BG,
            color: isUser ? '#fff' : AI_ACCENT,
          }}
        >
          {isUser ? <UserOutlined /> : <RobotOutlined />}
        </div>
      )}
      <div>
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
            {message.messageType === 'order_card' && message.payload ? (
              <OrderCard payload={message.payload as Parameters<typeof OrderCard>[0]['payload']} />
            ) : message.messageType === 'logistics_timeline' && message.payload ? (
              <LogisticsTimeline payload={message.payload as Parameters<typeof LogisticsTimeline>[0]['payload']} />
            ) : message.messageType === 'product_list' && message.payload ? (
              <ProductGrid payload={message.payload as Parameters<typeof ProductGrid>[0]['payload']} />
            ) : message.messageType === 'transfer' && message.payload ? (
              <TransferStatus payload={message.payload as Parameters<typeof TransferStatus>[0]['payload']} />
            ) : (
              message.content
            )}
          </Typography.Text>
        </div>
        {message.suggestions && message.suggestions.length > 0 && (
          <Space size={[6, 6]} wrap style={{ marginTop: 6 }}>
            {message.suggestions.map((s) => (
              <Tag key={s} style={{ cursor: 'pointer' }} onClick={() => onSuggestionClick?.(s)}>
                {s}
              </Tag>
            ))}
          </Space>
        )}
      </div>
    </div>
  );
}
