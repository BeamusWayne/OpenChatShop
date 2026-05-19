export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  suggestions?: string[];
  messageType?: string;
  payload?: Record<string, unknown>;
  streaming?: boolean;
}

export interface StreamEvent {
  type: 'typing' | 'chunk' | 'done' | 'error';
  data: {
    status?: string;
    content_delta?: string;
    message_type?: string;
    payload?: Record<string, unknown>;
    suggestions?: string[];
    requires_confirmation?: boolean;
    message?: string;
  };
}

export interface ConnectionState {
  connected: boolean;
  reconnecting: boolean;
}
