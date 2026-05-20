export interface QueueItem {
  request_id: string;
  session_id: string;
  reason: string;
  department: string;
  position: number;
  queued_at: string;
  priority: number;
}

export interface ActiveSession {
  session_id: string;
  request_id: string;
  reason: string;
  assigned_at: string | null;
}

export interface ChatMessage {
  id: string;
  role: 'agent' | 'customer' | 'system';
  content: string;
  timestamp: number;
  messageType?: string;
  payload?: Record<string, unknown>;
}

export interface AgentInfo {
  agent_id: string;
  name: string;
  department: string;
}
