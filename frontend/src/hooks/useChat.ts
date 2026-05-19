import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatMessage, ConnectionState, StreamEvent } from '../types/chat';

const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/chat/${crypto.randomUUID()}`;
const RECONNECT_DELAY = 3000;

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [connection, setConnection] = useState<ConnectionState>({
    connected: false,
    reconnecting: false,
  });
  const [isTyping, setIsTyping] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const streamingIdRef = useRef<string | null>(null);

  const addMessage = useCallback((msg: Omit<ChatMessage, 'id' | 'timestamp'>) => {
    const full: ChatMessage = {
      ...msg,
      id: crypto.randomUUID(),
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, full]);
    return full.id;
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      setConnection({ connected: true, reconnecting: false });
      addMessage({
        role: 'system',
        content: '欢迎使用 OpenChatShop 智能客服！请问有什么可以帮您？',
      });
    };

    ws.onmessage = (event) => {
      const evt: StreamEvent = JSON.parse(event.data);

      switch (evt.type) {
        case 'typing':
          setIsTyping(true);
          break;

        case 'chunk': {
          const delta = evt.data.content_delta ?? '';
          setIsTyping(false);

          if (!streamingIdRef.current) {
            const id = addMessage({
              role: 'assistant',
              content: delta,
              streaming: true,
            });
            streamingIdRef.current = id;
          } else {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === streamingIdRef.current
                  ? { ...m, content: m.content + delta }
                  : m,
              ),
            );
          }
          break;
        }

        case 'done': {
          setIsTyping(false);
          if (streamingIdRef.current) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === streamingIdRef.current
                  ? {
                      ...m,
                      streaming: false,
                      suggestions: evt.data.suggestions,
                      messageType: evt.data.message_type,
                      payload: evt.data.payload,
                    }
                  : m,
              ),
            );
            streamingIdRef.current = null;
          } else {
            const content =
              evt.data.payload?.text_fallback ??
              evt.data.payload?.content ??
              '操作完成';
            addMessage({
              role: 'assistant',
              content: typeof content === 'string' ? content : String(content),
              suggestions: evt.data.suggestions,
              messageType: evt.data.message_type,
              payload: evt.data.payload,
            });
          }
          break;
        }

        case 'error': {
          setIsTyping(false);
          streamingIdRef.current = null;
          addMessage({
            role: 'system',
            content: `错误：${evt.data.message ?? '未知错误'}`,
          });
          break;
        }
      }
    };

    ws.onclose = () => {
      setConnection({ connected: false, reconnecting: true });
      setTimeout(() => connect(), RECONNECT_DELAY);
    };

    ws.onerror = () => ws.close();
    wsRef.current = ws;
  }, [addMessage]);

  const sendMessage = useCallback(
    (content: string) => {
      if (!content.trim()) return;
      addMessage({ role: 'user', content: content.trim() });
      wsRef.current?.send(content.trim());
    },
    [addMessage],
  );

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  const clearMessages = useCallback(() => setMessages([]), []);

  return { messages, connection, isTyping, sendMessage, clearMessages };
}
