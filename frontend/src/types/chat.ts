export type SessionMode = 'ai_mode' | 'transfer_pending' | 'human_mode';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'agent';
  content: string;
  timestamp: number;
  suggestions?: string[];
  messageType?: string;
  payload?: Record<string, unknown>;
  streaming?: boolean;
  agentName?: string;
}

export interface StreamEvent {
  type: 'typing' | 'chunk' | 'done' | 'error' | 'agent_message' | 'transfer_status' | 'transfer_ended';
  data: {
    status?: string;
    content_delta?: string;
    message_type?: string;
    payload?: Record<string, unknown>;
    suggestions?: string[];
    requires_confirmation?: boolean;
    message?: string;
    content?: string;
    agent_name?: string;
    position?: number;
  };
}

export interface ConnectionState {
  connected: boolean;
  reconnecting: boolean;
}
