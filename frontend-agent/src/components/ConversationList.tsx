import { Tabs, List, Button, Tag, Typography, Empty } from 'antd';
import { UserOutlined, ClockCircleOutlined } from '@ant-design/icons';
import type { QueueItem, ActiveSession } from '../types/agent';

function formatWaitTime(queuedAt: string): string {
  const queued = new Date(queuedAt).getTime();
  const diff = Math.floor((Date.now() - queued) / 1000);
  if (diff < 60) return `${diff}秒`;
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟`;
  return `${Math.floor(diff / 3600)}小时`;
}

interface ConversationListProps {
  queueItems: QueueItem[];
  activeSessions: ActiveSession[];
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onAcceptSession: (sessionId: string) => Promise<void>;
}

export default function ConversationList({
  queueItems,
  activeSessions,
  selectedSessionId,
  onSelectSession,
  onAcceptSession,
}: ConversationListProps) {
  const items = [
    {
      key: 'queue',
      label: (
        <span>
          排队
          {queueItems.length > 0 && (
            <Tag color="orange" style={{ marginLeft: 6, fontSize: 11 }}>
              {queueItems.length}
            </Tag>
          )}
        </span>
      ),
      children: (
        <QueueTab
          items={queueItems}
          onAccept={onAcceptSession}
        />
      ),
    },
    {
      key: 'active',
      label: (
        <span>
          进行中
          {activeSessions.length > 0 && (
            <Tag color="blue" style={{ marginLeft: 6, fontSize: 11 }}>
              {activeSessions.length}
            </Tag>
          )}
        </span>
      ),
      children: (
        <ActiveTab
          sessions={activeSessions}
          selectedSessionId={selectedSessionId}
          onSelect={onSelectSession}
        />
      ),
    },
    {
      key: 'completed',
      label: '已结束',
      children: (
        <div style={{ padding: 24 }}>
          <Empty description="暂无已结束会话" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </div>
      ),
    },
  ];

  return (
    <Tabs
      items={items}
      style={{ height: '100%' }}
      tabBarStyle={{ padding: '0 16px', margin: 0 }}
    />
  );
}

interface QueueTabProps {
  items: QueueItem[];
  onAccept: (sessionId: string) => Promise<void>;
}

function QueueTab({ items, onAccept }: QueueTabProps) {
  if (items.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="暂无排队" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    );
  }

  return (
    <List
      dataSource={items}
      renderItem={(item) => (
        <List.Item
          style={{ padding: '8px 16px', cursor: 'pointer' }}
          actions={[
            <Button
              key="accept"
              type="primary"
              size="small"
              onClick={() => void onAccept(item.session_id)}
            >
              接入
            </Button>,
          ]}
        >
          <List.Item.Meta
            avatar={<UserOutlined style={{ fontSize: 20, color: '#ff5600' }} />}
            title={
              <Typography.Text ellipsis style={{ fontSize: 13 }}>
                {item.reason || '客户咨询'}
              </Typography.Text>
            }
            description={
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#9c9fa5' }}>
                <ClockCircleOutlined />
                {formatWaitTime(item.queued_at)}
                {item.department && <Tag style={{ marginLeft: 4, fontSize: 11 }}>{item.department}</Tag>}
              </div>
            }
          />
        </List.Item>
      )}
    />
  );
}

interface ActiveTabProps {
  sessions: ActiveSession[];
  selectedSessionId: string | null;
  onSelect: (sessionId: string) => void;
}

function ActiveTab({ sessions, selectedSessionId, onSelect }: ActiveTabProps) {
  if (sessions.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <Empty description="暂无进行中会话" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    );
  }

  return (
    <List
      dataSource={sessions}
      renderItem={(session) => {
        const isSelected = session.session_id === selectedSessionId;
        return (
          <List.Item
            onClick={() => onSelect(session.session_id)}
            style={{
              padding: '8px 16px',
              cursor: 'pointer',
              background: isSelected ? '#fff5eb' : 'transparent',
              borderLeft: isSelected ? '3px solid #ff5600' : '3px solid transparent',
            }}
          >
            <List.Item.Meta
              avatar={<UserOutlined style={{ fontSize: 20, color: '#ff5600' }} />}
              title={
                <Typography.Text ellipsis style={{ fontSize: 13 }}>
                  {session.reason || '客户咨询'}
                </Typography.Text>
              }
              description={
                <Typography.Text style={{ fontSize: 12, color: '#9c9fa5' }}>
                  {session.session_id.slice(0, 8)}
                </Typography.Text>
              }
            />
          </List.Item>
        );
      }}
    />
  );
}
