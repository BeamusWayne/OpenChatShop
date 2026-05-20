import { Card, Tag, Descriptions, theme } from 'antd';
import { ShoppingOutlined } from '@ant-design/icons';

const STATUS_COLORS: Record<string, string> = {
  pending: 'default',
  processing: 'processing',
  shipped: 'blue',
  delivered: 'success',
  cancelled: 'error',
  refunded: 'warning',
};

const STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  processing: '处理中',
  shipped: '已发货',
  delivered: '已送达',
  cancelled: '已取消',
  refunded: '已退款',
};

interface Props {
  payload: {
    order_id?: string;
    status?: string;
    items?: Array<{ name?: string; quantity?: number; price?: number }>;
    total_amount?: number;
    [key: string]: unknown;
  };
}

export default function OrderCard({ payload }: Props) {
  const { token } = theme.useToken();

  const status = payload.status ?? '';
  const statusLabel = STATUS_LABELS[status] ?? status;
  const statusColor = STATUS_COLORS[status] ?? 'default';
  const items = payload.items ?? [];

  return (
    <Card
      size="small"
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ShoppingOutlined style={{ color: token.colorPrimary }} />
          {payload.order_id ?? '订单详情'}
        </span>
      }
      style={{ maxWidth: 360 }}
    >
      <Descriptions column={1} size="small">
        <Descriptions.Item label="状态">
          <Tag color={statusColor}>{statusLabel}</Tag>
        </Descriptions.Item>
        {items.length > 0 && (
          <Descriptions.Item label="商品">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {items.map((item, i) => (
                <span key={i}>
                  {item.name ?? '商品'}
                  {item.quantity && item.quantity > 1 ? ` x${item.quantity}` : ''}
                </span>
              ))}
            </div>
          </Descriptions.Item>
        )}
        {payload.total_amount != null && (
          <Descriptions.Item label="金额">
            <span style={{ fontWeight: 600, color: token.colorPrimary }}>
              ¥{payload.total_amount.toFixed(2)}
            </span>
          </Descriptions.Item>
        )}
      </Descriptions>
    </Card>
  );
}
