import { useState, useEffect, useCallback, useRef } from 'react';
import type { QueueItem, ActiveSession, ChatMessage } from '../types/agent';

function mapHistoryRole(role: string): ChatMessage['role'] {
  if (role === 'assistant') return 'system';
  if (role === 'user') return 'customer';
  if (role === 'agent' || role === 'customer' || role === 'system') return role;
  return 'customer';
}

interface UseAgentReturn {
  queueItems: QueueItem[];
  activeSessions: ActiveSession[];
  selectedSessionId: string | null;
  messages: Record<string, ChatMessage[]>;
  connected: boolean;
  selectSession: (sessionId: string | null) => void;
  sendMessage: (sessionId: string, content: string) => void;
  acceptSession: (sessionId: string) => Promise<void>;
  completeSession: (sessionId: string) => Promise<void>;
  refreshQueue: () => Promise<void>;
  refreshActive: () => Promise<void>;
}

export function useAgent(agentId: string, agentName = '', agentDepartment = 'general'): UseAgentReturn {
  const [queueItems, setQueueItems] = useState<QueueItem[]>([]);
  const [activeSessions, setActiveSessions] = useState<ActiveSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Record<string, ChatMessage[]>>({});
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const messagesRef = useRef<Record<string, ChatMessage[]>>({});
  messagesRef.current = messages;

  const refreshQueue = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/agent/queue');
      if (res.ok) {
        const data = await res.json();
        setQueueItems(Array.isArray(data) ? data : data.queue ?? []);
      }
    } catch {
      // network error — will retry on next poll
    }
  }, []);

  const refreshActive = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/agent/active');
      if (res.ok) {
        const data = await res.json();
        setActiveSessions(Array.isArray(data) ? data : data.sessions ?? []);
      }
    } catch {
      // network error — will retry on next poll
    }
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const params = new URLSearchParams({ name: agentName, department: agentDepartment });
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/agent/${agentId}?${params}`);

    ws.onopen = () => {
      setConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string) as {
          type: string;
          data?: Record<string, unknown>;
        };

        switch (msg.type) {
          case 'queue_state': {
            const items = (msg.data?.queue ?? []) as QueueItem[];
            setQueueItems(items);
            break;
          }
          case 'new_request': {
            const item = msg.data as QueueItem | undefined;
            if (item) {
              setQueueItems((prev) => [...prev, item]);
            }
            break;
          }
          case 'request_assigned': {
            const sessionId = msg.data?.session_id as string | undefined;
            if (sessionId) {
              setQueueItems((prev) => prev.filter((q) => q.session_id !== sessionId));
              const newActive: ActiveSession = {
                session_id: sessionId,
                request_id: (msg.data?.request_id as string) ?? '',
                reason: (msg.data?.reason as string) ?? '',
                assigned_at: new Date().toISOString(),
              };
              setActiveSessions((prev) => [...prev, newActive]);
              setSelectedSessionId((prev) => prev ?? sessionId);
            }
            break;
          }
          case 'session_history': {
            const sid = msg.data?.session_id as string | undefined;
            const rawMessages = msg.data?.messages as Array<{
              role: string;
              content: string;
              message_type?: string;
              payload?: Record<string, unknown>;
              timestamp?: string;
            }> | undefined;
            if (sid && rawMessages && rawMessages.length > 0) {
              const history: ChatMessage[] = rawMessages.map((m) => ({
                id: `hist-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
                role: mapHistoryRole(m.role),
                content: m.content,
                messageType: m.message_type === 'transfer' ? 'transfer_status' : m.message_type,
                payload: m.payload,
                timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
              }));
              setMessages((prev) => ({
                ...prev,
                [sid]: [...history, ...(prev[sid] ?? [])],
              }));
            }
            break;
          }
          case 'transfer_completed': {
            const sessionId = msg.data?.session_id as string | undefined;
            if (sessionId) {
              setActiveSessions((prev) =>
                prev.filter((s) => s.session_id !== sessionId),
              );
              setSelectedSessionId((prev) =>
                prev === sessionId ? null : prev,
              );
              const endMsg: ChatMessage = {
                id: `end-${Date.now()}`,
                role: 'system',
                content: '会话已结束',
                timestamp: Date.now(),
              };
              setMessages((prev) => ({
                ...prev,
                [sessionId]: [...(prev[sessionId] ?? []), endMsg],
              }));
            }
            break;
          }
          case 'message_sent': {
            // Confirmation only — temp message already added in sendMessage.
            // No need to append another copy.
            break;
          }
          case 'customer_message': {
            const sid = msg.data?.session_id as string | undefined;
            const content = msg.data?.content as string | undefined;
            if (sid && content) {
              const customerMsg: ChatMessage = {
                id: `cust-${Date.now()}`,
                role: 'customer',
                content,
                timestamp: Date.now(),
              };
              setMessages((prev) => ({
                ...prev,
                [sid]: [...(prev[sid] ?? []), customerMsg],
              }));
            }
            break;
          }
          default:
            break;
        }
      } catch {
        // ignore malformed messages
      }
    };

    ws.onclose = () => {
      setConnected(false);
      reconnectTimerRef.current = setTimeout(() => {
        connect();
      }, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, [agentId, agentName, agentDepartment]);

  useEffect(() => {
    connect();
    void refreshQueue();
    void refreshActive();

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect, refreshQueue, refreshActive]);

  const selectSession = useCallback((sessionId: string | null) => {
    setSelectedSessionId(sessionId);
    // Load history for the selected session if not already loaded
    if (sessionId && messagesRef.current[sessionId] === undefined) {
      fetch(`/api/v1/agent/history/${sessionId}`)
        .then((res) => (res.ok ? res.json() : { messages: [] }))
        .then((data) => {
          const history: ChatMessage[] = (data.messages ?? []).map(
            (m: { role: string; content: string; message_type?: string; payload?: Record<string, unknown>; timestamp?: string }) => ({
              id: `hist-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
              role: mapHistoryRole(m.role),
              content: m.content,
              messageType: m.message_type === 'transfer' ? 'transfer_status' : m.message_type,
              payload: m.payload,
              timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
            }),
          );
          setMessages((prev) => {
            if (prev[sessionId] !== undefined) return prev;
            return { ...prev, [sessionId]: history };
          });
        })
        .catch(() => {});
    }
  }, []);

  const sendMessage = useCallback((sessionId: string, content: string) => {
    if (!content.trim()) return;

    const tempMessage: ChatMessage = {
      id: `temp-${Date.now()}`,
      role: 'agent',
      content,
      timestamp: Date.now(),
    };

    setMessages((prev) => ({
      ...prev,
      [sessionId]: [...(prev[sessionId] ?? []), tempMessage],
    }));

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'agent_message',
          data: { session_id: sessionId, content },
        }),
      );
    }
  }, []);

  const acceptSession = useCallback(async (sessionId: string) => {
    await fetch(`/api/v1/agent/accept/${sessionId}`, { method: 'POST' });
    await refreshQueue();
    await refreshActive();
    setSelectedSessionId(sessionId);

    // Fetch previous chat history for this session
    try {
      const res = await fetch(`/api/v1/agent/history/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        const history: ChatMessage[] = (data.messages ?? []).map(
          (m: { role: string; content: string; message_type?: string; payload?: Record<string, unknown>; timestamp?: string }) => ({
            id: `hist-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            role: mapHistoryRole(m.role),
            content: m.content,
            messageType: m.message_type === 'transfer' ? 'transfer_status' : m.message_type,
            payload: m.payload,
            timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
          }),
        );
        setMessages((prev) => ({
          ...prev,
          [sessionId]: [...history, ...(prev[sessionId] ?? [])],
        }));
      }
    } catch {
      // history fetch is best-effort
    }
  }, [refreshQueue, refreshActive]);

  const completeSession = useCallback(async (sessionId: string) => {
    await fetch(`/api/v1/agent/complete/${sessionId}`, { method: 'POST' });
    setActiveSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    setSelectedSessionId((prev) => (prev === sessionId ? null : prev));
  }, []);

  return {
    queueItems,
    activeSessions,
    selectedSessionId,
    messages,
    connected,
    selectSession,
    sendMessage,
    acceptSession,
    completeSession,
    refreshQueue,
    refreshActive,
  };
}
