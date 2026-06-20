import { useAppState, type PanelTab } from '@/state/AppState';
import { ErrorBoundary } from './ErrorBoundary';
import { ZoneDetail } from './panels/ZoneDetail';
import { SimulationPanel } from './panels/SimulationPanel';
import { ForecastPanel } from './panels/ForecastPanel';
import { GameTheoryPanel } from './panels/GameTheoryPanel';
import { AgentPanel } from './panels/AgentPanel';
import { ChatPanel } from './panels/ChatPanel';

interface RightPanelProps {
  onClose: () => void;
}

const TABS: { id: PanelTab; label: string }[] = [
  { id: 'details', label: 'Zone' },
  { id: 'sim', label: 'Simulate' },
  { id: 'forecast', label: 'Forecast' },
  { id: 'game', label: 'Game' },
  { id: 'agent', label: 'Agent' },
  { id: 'chat', label: 'Assistant' },
];

export function RightPanel({ onClose }: RightPanelProps) {
  const { panel, setPanel } = useAppState();
  return (
    <aside className="right-panel">
      <div className="panel-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`panel-tab ${panel === t.id ? 'active' : ''}`}
            onClick={() => setPanel(t.id)}
          >
            {t.label}
          </button>
        ))}
        <button className="panel-close-btn" onClick={onClose} title="Close panel">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
      <div className="panel-content active">
        <ErrorBoundary>
          {panel === 'details' && <ZoneDetail />}
          {panel === 'sim' && <SimulationPanel />}
          {panel === 'forecast' && <ForecastPanel />}
          {panel === 'game' && <GameTheoryPanel />}
          {panel === 'agent' && <AgentPanel />}
          {panel === 'chat' && <ChatPanel />}
        </ErrorBoundary>
      </div>
    </aside>
  );
}

