import { Card, Row, Col, Typography, Tag, theme } from 'antd';
import { ShoppingOutlined } from '@ant-design/icons';

interface Product {
  id?: string;
  name?: string;
  price?: number;
  category?: string;
  image_url?: string;
}

interface Props {
  payload: {
    products?: Product[];
    total?: number;
    [key: string]: unknown;
  };
}

export default function ProductGrid({ payload }: Props) {
  const { token } = theme.useToken();
  const products = payload.products ?? [];

  return (
    <Card
      size="small"
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ShoppingOutlined style={{ color: '#ff5600' }} />
          商品搜索
          {payload.total != null && (
            <Tag style={{ marginLeft: 4 }}>共 {payload.total} 件</Tag>
          )}
        </span>
      }
      style={{ maxWidth: 480 }}
    >
      {products.length > 0 ? (
        <Row gutter={[8, 8]}>
          {products.slice(0, 6).map((p) => (
            <Col key={p.id ?? p.name} span={8}>
              <div
                style={{
                  border: `1px solid ${token.colorBorderSecondary}`,
                  borderRadius: token.borderRadius,
                  padding: 8,
                  textAlign: 'center',
                  height: '100%',
                }}
              >
                {p.image_url ? (
                  <img
                    src={p.image_url}
                    alt={p.name}
                    style={{ width: 48, height: 48, objectFit: 'cover', borderRadius: 4, marginBottom: 4 }}
                  />
                ) : (
                  <div
                    style={{
                      width: 48,
                      height: 48,
                      background: token.colorBgContainer,
                      borderRadius: 4,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      margin: '0 auto 4px',
                      fontSize: 20,
                      color: token.colorTextQuaternary,
                    }}
                  >
                    <ShoppingOutlined />
                  </div>
                )}
                <Typography.Text
                  ellipsis
                  style={{ display: 'block', fontSize: 12, lineHeight: '16px' }}
                >
                  {p.name ?? '商品'}
                </Typography.Text>
                <Typography.Text
                  strong
                  style={{ color: '#ff5600', fontSize: 13 }}
                >
                  ¥{p.price?.toFixed(2) ?? '--'}
                </Typography.Text>
              </div>
            </Col>
          ))}
        </Row>
      ) : (
        <Typography.Text type="secondary">未找到相关商品</Typography.Text>
      )}
    </Card>
  );
}
