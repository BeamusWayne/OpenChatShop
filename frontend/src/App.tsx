import { ConfigProvider } from 'antd';
import { StyleProvider } from '@ant-design/cssinjs';
import useGlassTheme from './theme/glassTheme';
import ChatWindow from './components/ChatWindow';

export default function App() {
  const configProps = useGlassTheme();

  return (
    <StyleProvider layer>
      <ConfigProvider {...configProps}>
        <ChatWindow />
      </ConfigProvider>
    </StyleProvider>
  );
}
