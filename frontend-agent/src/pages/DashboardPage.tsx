import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Spin, Result } from 'antd';
import type { AgentInfo } from '../types/agent';
import { useAgent } from '../hooks/useAgent';
import AgentHeader from '../components/AgentHeader';
import ConversationList from '../components/ConversationList';
import AgentChat from '../components/AgentChat';
import CustomerPanel from '../components/CustomerPanel';

export default function DashboardPage() {
  const navigate = useNavigate();
  const [agentInfo, setAgentInfo] = useState<AgentInfo | null>(null);
  const [panelVisible, setPanelVisible] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem('agent_info');
    if (!stored) {
      navigate('/');
      return;
    }
    try {
      setAgentInfo(JSON.parse(stored) as AgentInfo);
    } catch {
      localStorage.removeItem('agent_info');
      navigate('/');
    }
  }, [navigate]);

  if (!agentInfo) {
    return (
      <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <DashboardContent
      agentInfo={agentInfo}
      onTogglePanel={() => setPanelVisible((v) => !v)}
      panelVisible={panelVisible}
      onLogout={() => {
        localStorage.removeItem('agent_info');
        navigate('/');
      }}
    />
  );
}

interface DashboardContentProps {
  agentInfo: AgentInfo;
  onTogglePanel: () => void;
  panelVisible: boolean;
  onLogout: () => void;
}

function DashboardContent({ agentInfo, panelVisible, onLogout }: DashboardContentProps) {
  const agent = useAgent(agentInfo.agent_id);

  const selectedSession = agent.activeSessions.find(
    (s) => s.session_id === agent.selectedSessionId,
  );

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#f5f1ec' }}>
      <AgentHeader
        agentInfo={agentInfo}
        connected={agent.connected}
        onLogout={onLogout}
      />

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left: Conversation List */}
        <div style={{ width: 280, borderRight: '1px solid #ebe7e1', background: '#fff', overflow: 'auto' }}>
          <ConversationList
            queueItems={agent.queueItems}
            activeSessions={agent.activeSessions}
            selectedSessionId={agent.selectedSessionId}
            onSelectSession={agent.selectSession}
            onAcceptSession={agent.acceptSession}
          />
        </div>

        {/* Center: Chat */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          {agent.selectedSessionId ? (
            <AgentChat
              sessionId={agent.selectedSessionId}
              messages={agent.messages[agent.selectedSessionId] ?? []}
              onSendMessage={(content) => agent.sendMessage(agent.selectedSessionId, content)}
            />
          ) : (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Result
                title="请选择一个会话"
                subTitle="从左侧列表中选择排队中的客户或正在进行的会话"
              />
            </div>
          )}
        </div>

        {/* Right: Customer Panel */}
        {panelVisible && (
          <div style={{ width: 300, borderLeft: '1px solid #ebe7e1', background: '#fff', overflow: 'auto' }}>
            {selectedSession ? (
              <CustomerPanel
                session={selectedSession}
                onComplete={() => agent.completeSession(selectedSession.session_id)}
              />
            ) : (
              <div style={{ padding: 24, textAlign: 'center', color: '#9c9fa5' }}>
                选择一个进行中的会话查看客户信息
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
