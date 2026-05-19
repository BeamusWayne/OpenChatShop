import { ConfigProvider, theme } from 'antd';
import ChatWindow from './components/ChatWindow';

export default function App() {
  const configProps = { theme: { algorithm: theme.defaultAlgorithm } };

  return (
    <ConfigProvider {...configProps}>
      <ChatWindow />
    </ConfigProvider>
  );
}
