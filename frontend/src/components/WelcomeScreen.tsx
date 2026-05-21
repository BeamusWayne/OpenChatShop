import { Card, theme } from 'antd';
import {
  RobotOutlined,
  SearchOutlined,
  CarOutlined,
  UndoOutlined,
  HeadsetOutlined,
} from '@ant-design/icons';

interface WelcomeScreenProps {
  onAction: (text: string) => void;
}

const CAPABILITIES = [
  { icon: <SearchOutlined />, label: '查询订单', text: '帮我查一下最近的订单', color: '#ff5600' },
  { icon: <CarOutlined />, label: '物流追踪', text: '物流查询', color: '#1677ff' },
  { icon: <UndoOutlined />, label: '退换货', text: '我要退款', color: '#52c41a' },
  { icon: <SearchOutlined />, label: '搜索商品', text: '推荐一些热门商品', color: '#722ed1' },
  { icon: <HeadsetOutlined />, label: '转人工', text: '转人工客服', color: '#fa8c16' },
];

export default function WelcomeScreen({ onAction }: WelcomeScreenProps) {
  const { token } = theme.useToken();

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        flex: 1,
        padding: '40px 20px',
        gap: 24,
      }}
    >
      <div
        style={{
          width: 72,
          height: 72,
          borderRadius: '50%',
          background: 'linear-gradient(135deg, #ff5600 0%, #ff8533 100%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontSize: 36,
          boxShadow: '0 4px 16px rgba(255, 86, 0, 0.3)',
        }}
      >
        <RobotOutlined />
      </div>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 20, fontWeight: 600, color: token.colorText, marginBottom: 8 }}>
          你好，我是 OpenChatShop 智能客服
        </div>
        <div style={{ fontSize: 14, color: token.colorTextSecondary, lineHeight: 1.6 }}>
          7x24 小时在线，随时为您服务
        </div>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
          gap: 12,
          width: '100%',
          maxWidth: 480,
        }}
      >
        {CAPABILITIES.map((cap) => (
          <Card
            key={cap.label}
            hoverable
            size="small"
            onClick={() => onAction(cap.text)}
            aria-label={cap.label}
            style={{ textAlign: 'center', cursor: 'pointer' }}
            bodyStyle={{ padding: '16px 8px' }}
          >
            <div style={{ fontSize: 24, color: cap.color, marginBottom: 8 }}>{cap.icon}</div>
            <div style={{ fontSize: 13, color: token.colorText }}>{cap.label}</div>
          </Card>
        ))}
      </div>
    </div>
  );
}
