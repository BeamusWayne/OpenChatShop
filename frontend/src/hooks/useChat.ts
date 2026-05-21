import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatMessage, ConnectionState, SessionMode, StreamEvent } from '../types/chat';

const SESSION_ID = crypto.randomUUID();
const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/chat/${SESSION_ID}`;
const STORAGE_KEY = `openchatshop_messages_${SESSION_ID}`;
const MAX_STORED_MESSAGES = 200;
const RECONNECT_DELAY = 3000;

function loadSavedMessages(): ChatMessage[] {
  try {
    const saved = sessionStorage.getItem(STORAGE_KEY);
    if (!saved) return [];
    const parsed: unknown = JSON.parse(saved);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (m: unknown): m is ChatMessage =>
        typeof m === 'object' &&
        m !== null &&
        'role' in m &&
        'content' in m,
    );
  } catch {
    return [];
  }
}

function persistMessages(msgs: ChatMessage[]): void {
  try {
    const toSave = msgs.slice(-MAX_STORED_MESSAGES);
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
  } catch {
    // quota exceeded or incognito restriction — ignore
  }
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>(() => loadSavedMessages());

  useEffect(() => {
    if (messages.length > 0) {
      persistMessages(messages);
    }
  }, [messages]);

  const [connection, setConnection] = useState<ConnectionState>({
    connected: false,
    reconnecting: false,
  });
  const [isTyping, setIsTyping] = useState(false);
  const [sessionMode, setSessionMode] = useState<SessionMode>('ai_mode');
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

        case 'agent_message': {
          setIsTyping(false);
          addMessage({
            role: 'agent',
            content: evt.data.content ?? '',
            agentName: evt.data.agent_name,
          });
          break;
        }

        case 'transfer_status': {
          setIsTyping(false);
          const status = evt.data.status ?? 'waiting';
          if (status === 'connected') {
            setSessionMode('human_mode');
            addMessage({
              role: 'system',
              content: `客服 ${evt.data.agent_name ?? ''} 已为您服务`,
              messageType: 'transfer',
              payload: {
                status: 'assigned',
                agent_name: evt.data.agent_name,
              },
            });
          } else {
            setSessionMode('transfer_pending');
            addMessage({
              role: 'system',
              content: '正在为您转接人工客服，请稍候...',
              messageType: 'transfer',
              payload: {
                status: 'waiting',
                position: evt.data.position,
              },
            });
          }
          break;
        }

        case 'transfer_ended': {
          setIsTyping(false);
          setSessionMode('ai_mode');
          addMessage({
            role: 'system',
            content: evt.data.message ?? '人工服务已结束，已回到智能助手模式。',
          });
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

  const clearMessages = useCallback(() => {
    setMessages([]);
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }, []);

  return { messages, connection, isTyping, sessionMode, sendMessage, clearMessages };
}
