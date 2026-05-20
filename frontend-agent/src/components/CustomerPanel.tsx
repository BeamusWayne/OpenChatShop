import { Card, Descriptions, Button, Typography, Tag } from 'antd';
import {
  CheckCircleOutlined,
  UserOutlined,
  FieldTimeOutlined,
} from '@ant-design/icons';
import type { ActiveSession } from '../types/agent';

interface CustomerPanelProps {
  session: ActiveSession;
  onComplete: () => void;
}

export default function CustomerPanel({ session, onComplete }: CustomerPanelProps) {
  return (
    <div style={{ padding: 16 }}>
      <Card
        size="small"
        title={
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <UserOutlined />
            会话信息
          </span>
        }
        style={{ marginBottom: 16 }}
      >
        <Descriptions column={1} size="small">
          <Descriptions.Item label="会话 ID">
            <Typography.Text copyable style={{ fontSize: 12 }}>
              {session.session_id}
            </Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="渠道">
            <Tag>在线</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="排队原因">
            {session.reason || '--'}
          </Descriptions.Item>
          {session.assigned_at && (
            <Descriptions.Item label="接入时间">
              <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <FieldTimeOutlined />
                {new Date(session.assigned_at).toLocaleTimeString('zh-CN')}
              </span>
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <Button
          danger
          block
          icon={<CheckCircleOutlined />}
          onClick={() => void onComplete()}
        >
          结束服务
        </Button>
      </div>
    </div>
  );
}
