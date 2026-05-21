import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Form, Input, Select, Button, Card, Typography, message } from 'antd';
import { UserOutlined, TeamOutlined, LockOutlined } from '@ant-design/icons';
import type { AgentInfo } from '../types/agent';

interface LoginFormValues {
  name: string;
  department: string;
  secret?: string;
}

const DEPARTMENT_OPTIONS = [
  { value: 'general', label: '综合客服' },
  { value: 'refund', label: '退款售后' },
  { value: 'tech', label: '技术支持' },
];

export default function LoginPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (values: LoginFormValues) => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/agent/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      });

      if (!res.ok) {
        throw new Error(`注册失败: ${res.status}`);
      }

      const data = (await res.json()) as AgentInfo;
      localStorage.setItem('agent_info', JSON.stringify(data));
      navigate('/dashboard');
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : '注册失败，请重试';
      void message.error(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #f5f1ec 0%, #ede8e1 100%)',
      }}
    >
      <Card
        style={{ width: 400, borderRadius: 16 }}
        styles={{ body: { padding: 32 } }}
      >
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <TeamOutlined style={{ fontSize: 36, color: '#ff5600', marginBottom: 12 }} />
          <Typography.Title level={3} style={{ margin: 0 }}>
            客服后台
          </Typography.Title>
          <Typography.Text type="secondary">
            登录以开始服务客户
          </Typography.Text>
        </div>

        <Form<LoginFormValues>
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{ department: 'general' }}
          size="large"
        >
          <Form.Item
            name="name"
            label="客服名称"
            rules={[{ required: true, message: '请输入客服名称' }]}
          >
            <Input
              prefix={<UserOutlined />}
              placeholder="请输入您的名称"
            />
          </Form.Item>

          <Form.Item
            name="department"
            label="所属部门"
            rules={[{ required: true, message: '请选择部门' }]}
          >
            <Select options={DEPARTMENT_OPTIONS} />
          </Form.Item>

          <Form.Item
            name="secret"
            label="坐席密码"
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="请输入坐席密码（可选）"
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              size="large"
            >
              上线
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
