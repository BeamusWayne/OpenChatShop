import { Card, Badge, Typography, theme } from 'antd';
import {
  CustomerServiceOutlined,
  ClockCircleOutlined,
  UserOutlined,
} from '@ant-design/icons';

interface Props {
  payload: {
    reason?: string;
    department?: string;
    estimated_wait_seconds?: number;
    queue_position?: number;
    agent_name?: string;
    status?: 'queued' | 'assigned' | 'active' | 'completed';
    [key: string]: unknown;
  };
}

function formatWait(seconds: number): string {
  if (seconds < 60) return `${seconds} 秒`;
  const m = Math.ceil(seconds / 60);
  return `${m} 分钟`;
}

export default function TransferStatus({ payload }: Props) {
  const { token } = theme.useToken();

  const agentName = payload.agent_name;
  const queuePos = payload.queue_position;
  const waitSeconds = payload.estimated_wait_seconds ?? 120;
  const isAssigned = !!agentName || payload.status === 'assigned' || payload.status === 'active';

  return (
    <Card
      size="small"
      style={{
        maxWidth: 340,
        background: isAssigned ? '#f6ffed' : token.colorBgContainer,
        borderColor: isAssigned ? '#b7eb8f' : token.colorBorderSecondary,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: '50%',
            background: isAssigned ? '#f6ffed' : '#fff5eb',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: isAssigned ? '#52c41a' : '#ff5600',
            fontSize: 20,
            flexShrink: 0,
          }}
        >
          <CustomerServiceOutlined />
        </div>
        <div style={{ flex: 1 }}>
          {isAssigned ? (
            <>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>
                <UserOutlined style={{ marginRight: 4 }} />
                客服 {agentName ?? '已接入'}
              </div>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                已接入人工客服。
              </Typography.Text>
            </>
          ) : (
            <>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>
                <ClockCircleOutlined style={{ marginRight: 4 }} />
                正在转接人工客服
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {queuePos != null && (
                  <Badge
                    count={`排队第 ${queuePos} 位`}
                    style={{ backgroundColor: '#ff5600' }}
                  />
                )}
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                  预计等待 {formatWait(waitSeconds)}
                </Typography.Text>
              </div>
              {payload.reason && (
                <Typography.Text
                  type="secondary"
                  style={{ fontSize: 12, display: 'block', marginTop: 4 }}
                >
                  转接原因：{payload.reason}
                </Typography.Text>
              )}
            </>
          )}
        </div>
      </div>
    </Card>
  );
}
