import { Typography, Space, Tag } from 'antd';
import { RobotOutlined, UserOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { createStyles } from 'antd-style';
import type { ChatMessage } from '../types/chat';

const useStyles = createStyles(({ css, token }) => ({
  row: css({
    display: 'flex',
    gap: 8,
    maxWidth: '85%',
    animation: 'fadeIn 0.3s ease',
    [`@keyframes fadeIn`]: {
      from: { opacity: 0, transform: 'translateY(8px)' },
      to: { opacity: 1, transform: 'translateY(0)' },
    },
  }),
  userRow: css({ alignSelf: 'flex-end', flexDirection: 'row-reverse' }),
  assistantRow: css({ alignSelf: 'flex-start' }),
  systemRow: css({ alignSelf: 'center', maxWidth: '95%' }),
  avatar: css({
    width: 36,
    height: 36,
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
    fontSize: 18,
  }),
  userAvatar: css({
    background: `linear-gradient(135deg, ${token.colorPrimary}, ${token.colorPrimaryActive})`,
    color: '#fff',
  }),
  assistantAvatar: css({
    background: 'linear-gradient(135deg, #8b5cf6, #6366f1)',
    color: '#fff',
  }),
  bubble: css({
    padding: '10px 14px',
    borderRadius: token.borderRadiusLG,
    lineHeight: 1.6,
    wordBreak: 'break-word',
    whiteSpace: 'pre-wrap',
  }),
  userBubble: css({
    background: `linear-gradient(135deg, ${token.colorPrimary}, ${token.colorPrimaryHover})`,
    color: '#fff',
    borderTopRightRadius: 4,
  }),
  assistantBubble: css({
    background: `color-mix(in srgb, ${token.colorBgContainer} 60%, transparent)`,
    backdropFilter: 'blur(8px)',
    border: `1px solid rgba(255, 255, 255, 0.15)`,
    borderTopLeftRadius: 4,
  }),
  systemBubble: css({
    background: `color-mix(in srgb, ${token.colorWarningBg} 40%, transparent)`,
    backdropFilter: 'blur(8px)',
    border: `1px solid rgba(255, 255, 255, 0.1)`,
    borderRadius: token.borderRadiusLG,
    fontSize: 13,
    color: token.colorTextSecondary,
  }),
  suggestionTag: css({
    cursor: 'pointer',
    backdropFilter: 'blur(4px)',
    background: 'rgba(255,255,255,0.1)',
    borderColor: 'rgba(255,255,255,0.2)',
    '&:hover': {
      background: 'rgba(255,255,255,0.2)',
      borderColor: 'rgba(255,255,255,0.3)',
    },
  }),
  streaming: css({
    '&::after': {
      content: '"|"',
      animation: 'blink 1s step-end infinite',
    },
    [`@keyframes blink`]: { '50%': { opacity: 0 } },
  }),
}));

interface Props {
  message: ChatMessage;
  onSuggestionClick?: (text: string) => void;
}

export default function MessageBubble({ message, onSuggestionClick }: Props) {
  const { styles } = useStyles();

  const roleClass =
    message.role === 'user' ? styles.userRow
      : message.role === 'assistant' ? styles.assistantRow
      : styles.systemRow;

  const bubbleClass =
    message.role === 'user' ? styles.userBubble
      : message.role === 'assistant' ? styles.assistantBubble
      : styles.systemBubble;

  const avatarClass =
    message.role === 'user' ? styles.userAvatar : styles.assistantAvatar;

  const icon =
    message.role === 'user' ? <UserOutlined />
      : message.role === 'assistant' ? <RobotOutlined />
      : <InfoCircleOutlined />;

  return (
    <div className={`${styles.row} ${roleClass}`}>
      {message.role !== 'system' && (
        <div className={`${styles.avatar} ${avatarClass}`}>{icon}</div>
      )}
      <div>
        <div className={`${styles.bubble} ${bubbleClass} ${message.streaming ? styles.streaming : ''}`}>
          <Typography.Text style={{ color: 'inherit' }}>
            {message.content}
          </Typography.Text>
        </div>
        {message.suggestions && message.suggestions.length > 0 && (
          <Space size={[6, 6]} wrap style={{ marginTop: 6 }}>
            {message.suggestions.map((s) => (
              <Tag key={s} className={styles.suggestionTag} onClick={() => onSuggestionClick?.(s)}>
                {s}
              </Tag>
            ))}
          </Space>
        )}
      </div>
    </div>
  );
}
