import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatMessage, ConnectionState, SessionMode, StreamEvent } from '../types/chat';

const SESSION_ID_KEY = 'openchatshop_session_id';
const INITIAL_RECONNECT_DELAY = 3000;
const MAX_RECONNECT_DELAY = 60000;
const HEARTBEAT_INTERVAL = 30000;
const HEARTBEAT_TIMEOUT = 10000;
const MAX_STORED_MESSAGES = 200;

function getReconnectDelay(retryCount: number): number {
  return Math.min(INITIAL_RECONNECT_DELAY * Math.pow(2, retryCount), MAX_RECONNECT_DELAY);
}

function getOrCreateSessionId(): string {
  const stored = localStorage.getItem(SESSION_ID_KEY);
  if (stored) return stored;
  const id = crypto.randomUUID();
  localStorage.setItem(SESSION_ID_KEY, id);
  return id;
}

function loadSavedMessages(sessionId: string): ChatMessage[] {
  try {
    const storageKey = `openchatshop_messages_${sessionId}`;
    const saved = sessionStorage.getItem(storageKey);
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

function persistMessages(sessionId: string, msgs: ChatMessage[]): void {
  try {
    const storageKey = `openchatshop_messages_${sessionId}`;
    const toSave = msgs.slice(-MAX_STORED_MESSAGES);
    sessionStorage.setItem(storageKey, JSON.stringify(toSave));
  } catch {
    // quota exceeded or incognito restriction — ignore
  }
}

export function useChat() {
  const sessionIdRef = useRef<string>(getOrCreateSessionId());
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    loadSavedMessages(sessionIdRef.current),
  );

  useEffect(() => {
    if (messages.length > 0) {
      persistMessages(sessionIdRef.current, messages);
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
  const retryCountRef = useRef(0);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const heartbeatTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingMessagesRef = useRef<string[]>([]);

  const addMessage = useCallback((msg: Omit<ChatMessage, 'id' | 'timestamp'>) => {
    const full: ChatMessage = {
      ...msg,
      id: crypto.randomUUID(),
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, full]);
    return full.id;
  }, []);

  const clearTimers = useCallback(() => {
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
    if (heartbeatTimeoutRef.current) {
      clearTimeout(heartbeatTimeoutRef.current);
      heartbeatTimeoutRef.current = null;
    }
  }, []);

  const drainPendingMessages = useCallback((ws: WebSocket) => {
    const pending = [...pendingMessagesRef.current];
    pendingMessagesRef.current = [];
    for (const msg of pending) {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(msg);
      } else {
        pendingMessagesRef.current.push(msg);
      }
    }
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const sessionId = sessionIdRef.current;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat/${sessionId}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      retryCountRef.current = 0;
      setConnection({ connected: true, reconnecting: false });
      drainPendingMessages(ws);

      // Start heartbeat
      clearTimers();
      heartbeatTimerRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'heartbeat' }));
          heartbeatTimeoutRef.current = setTimeout(() => {
            clearTimers();
            ws.close();
          }, HEARTBEAT_TIMEOUT);
        }
      }, HEARTBEAT_INTERVAL);

      addMessage({
        role: 'system',
        content: '欢迎使用 OpenChatShop 智能客服！请问有什么可以帮您？',
      });
    };

    ws.onmessage = (event) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(event.data);
      } catch {
        return;
      }

      // Handle heartbeat response — clear the timeout
      if (
        typeof parsed === 'object' &&
        parsed !== null &&
        'type' in parsed &&
        (parsed as { type: string }).type === 'heartbeat'
      ) {
        if (heartbeatTimeoutRef.current) {
          clearTimeout(heartbeatTimeoutRef.current);
          heartbeatTimeoutRef.current = null;
        }
        return;
      }

      const evt = parsed as StreamEvent;

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
      clearTimers();
      setConnection({ connected: false, reconnecting: true });
      const delay = getReconnectDelay(retryCountRef.current);
      retryCountRef.current += 1;
      setTimeout(() => connect(), delay);
    };

    ws.onerror = () => ws.close();
    wsRef.current = ws;
  }, [addMessage, clearTimers, drainPendingMessages]);

  const sendMessage = useCallback(
    (content: string) => {
      if (!content.trim()) return;
      const trimmed = content.trim();
      addMessage({ role: 'user', content: trimmed });
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(trimmed);
      } else {
        pendingMessagesRef.current.push(trimmed);
      }
    },
    [addMessage],
  );

  useEffect(() => {
    connect();
    return () => {
      clearTimers();
      wsRef.current?.close();
    };
  }, [connect, clearTimers]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    try {
      const storageKey = `openchatshop_messages_${sessionIdRef.current}`;
      sessionStorage.removeItem(storageKey);
      localStorage.removeItem(SESSION_ID_KEY);
    } catch {
      // ignore
    }
  }, []);

  return { messages, connection, isTyping, sessionMode, sendMessage, clearMessages };
}
