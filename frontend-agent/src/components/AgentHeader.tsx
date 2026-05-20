import { Layout, Typography, Badge, Tag, Button } from 'antd';
import { LogoutOutlined, UserOutlined } from '@ant-design/icons';
import type { AgentInfo } from '../types/agent';

const DEPARTMENT_LABELS: Record<string, string> = {
  general: '综合客服',
  refund: '退款售后',
  tech: '技术支持',
};

interface AgentHeaderProps {
  agentInfo: AgentInfo;
  connected: boolean;
  onLogout: () => void;
}

export default function AgentHeader({ agentInfo, connected, onLogout }: AgentHeaderProps) {
  return (
    <Layout.Header
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 24px',
        background: '#fff',
        borderBottom: '1px solid #ebe7e1',
        height: 56,
        lineHeight: '56px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          OpenChatShop
        </Typography.Title>
        <Tag color="orange">{DEPARTMENT_LABELS[agentInfo.department] ?? agentInfo.department}</Tag>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Badge status={connected ? 'success' : 'error'} />
          <UserOutlined />
          <Typography.Text>{agentInfo.name}</Typography.Text>
        </div>
        <Button
          type="text"
          icon={<LogoutOutlined />}
          onClick={onLogout}
        >
          下线
        </Button>
      </div>
    </Layout.Header>
  );
}
