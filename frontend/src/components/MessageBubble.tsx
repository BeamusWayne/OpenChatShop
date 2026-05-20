import { Typography, Space, Tag, theme } from 'antd';
import { RobotOutlined, UserOutlined } from '@ant-design/icons';
import type { ChatMessage } from '../types/chat';

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
            background: isUser ? token.colorPrimary : token.colorPrimaryBg,
            color: isUser ? '#fff' : token.colorPrimary,
          }}
        >
          {isUser ? <UserOutlined /> : <RobotOutlined />}
        </div>
      )}
      <div>
        <div
          style={{
            padding: '10px 14px',
            borderRadius: token.borderRadiusLG,
            ...(isUser
              ? {
                  background: token.colorPrimary,
                  color: token.colorWhite,
                  borderTopRightRadius: 4,
                }
              : isAssistant
                ? {
                    background: token.colorBgContainer,
                    border: `1px solid ${token.colorBorderSecondary}`,
                    borderTopLeftRadius: 4,
                  }
                : {
                    background: token.colorInfoBg,
                    borderRadius: token.borderRadiusLG,
                    fontSize: 13,
                    color: token.colorTextSecondary,
                  }),
            lineHeight: 1.6,
            wordBreak: 'break-word',
            whiteSpace: 'pre-wrap',
          }}
        >
          <Typography.Text style={{ color: 'inherit' }}>
            {message.content}
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
