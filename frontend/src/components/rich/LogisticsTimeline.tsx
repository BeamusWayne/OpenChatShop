import { Card, Timeline, Typography, theme } from 'antd';
import { CarOutlined, CheckCircleOutlined, ClockCircleOutlined } from '@ant-design/icons';

interface TimelineEntry {
  time?: string;
  status?: string;
  location?: string;
  description?: string;
}

interface Props {
  payload: {
    order_id?: string;
    carrier?: string;
    tracking_number?: string;
    steps?: TimelineEntry[];
    timeline?: TimelineEntry[];
    [key: string]: unknown;
  };
}

export default function LogisticsTimeline({ payload }: Props) {
  const { token } = theme.useToken();

  const entries = payload.steps ?? payload.timeline ?? [];

  return (
    <Card
      size="small"
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <CarOutlined style={{ color: token.colorPrimary }} />
          物流追踪
        </span>
      }
      extra={
        payload.tracking_number && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {payload.carrier} {payload.tracking_number}
          </Typography.Text>
        )
      }
      style={{ maxWidth: 400 }}
    >
      {entries.length > 0 ? (
        <Timeline
          items={entries.map((entry, i) => ({
            color: i === 0 ? token.colorPrimary : 'gray',
            dot: i === 0 ? <ClockCircleOutlined style={{ fontSize: 16 }} /> : undefined,
            children: (
              <div>
                <div style={{ fontWeight: i === 0 ? 600 : 400 }}>
                  {entry.status ?? entry.description ?? '更新'}
                </div>
                <div style={{ fontSize: 12, color: token.colorTextSecondary }}>
                  {entry.time && <span>{entry.time}</span>}
                  {entry.location && <span> · {entry.location}</span>}
                </div>
              </div>
            ),
          }))}
        />
      ) : (
        <Typography.Text type="secondary">暂无物流轨迹</Typography.Text>
      )}
    </Card>
  );
}
