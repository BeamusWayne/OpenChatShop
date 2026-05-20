import { ConfigProvider } from 'antd';
import { openChatShopTheme } from './theme/intercomTheme';
import ChatWindow from './components/ChatWindow';

export default function App() {
  return (
    <ConfigProvider theme={openChatShopTheme}>
      <ChatWindow />
    </ConfigProvider>
  );
}
