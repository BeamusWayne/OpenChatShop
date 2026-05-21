import { Tag } from 'antd';

const PRESET_REPLIES = [
  '您好，请问有什么可以帮您？',
  '请您提供一下订单号。',
  '好的，我来帮您处理。',
  '请稍等，正在为您查询。',
  '已经为您处理完成，还有其他问题吗？',
  '非常抱歉给您带来不便。',
  '感谢您的耐心等待。',
  '请问还有其他需要帮助的吗？',
];

interface QuickRepliesProps {
  onSelect: (text: string) => void;
}

export default function QuickReplies({ onSelect }: QuickRepliesProps) {
  return (
    <div style={{ padding: '8px 24px', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {PRESET_REPLIES.map((r) => (
        <Tag
          key={r}
          style={{ cursor: 'pointer', fontSize: 12 }}
          color="default"
          onClick={() => onSelect(r)}
        >
          {r}
        </Tag>
      ))}
    </div>
  );
}
