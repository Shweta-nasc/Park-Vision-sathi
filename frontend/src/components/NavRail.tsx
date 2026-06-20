import { useAppState, type PanelTab } from '@/state/AppState';

interface NavRailProps {
  panelOpen: boolean;
  onTogglePanel: (open: boolean) => void;
}

const ICONS: Record<string, JSX.Element> = {
  map: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6" />
      <line x1="8" y1="2" x2="8" y2="18" />
      <line x1="16" y1="6" x2="16" y2="22" />
    </svg>
  ),
  sim: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  ),
  forecast: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 3v18h18" />
      <path d="m19 9-5 5-4-4-3 3" />
    </svg>
  ),
  game: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <path d="M6 12h4M8 10v4M15 13h.01M18 11h.01" />
    </svg>
  ),
  chat: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  ),
};

const ITEMS: { tab: PanelTab; label: string; icon: keyof typeof ICONS }[] = [
  { tab: 'details', label: 'Zone', icon: 'map' },
  { tab: 'sim', label: 'Sim', icon: 'sim' },
  { tab: 'forecast', label: 'Forecast', icon: 'forecast' },
  { tab: 'game', label: 'Game', icon: 'game' },
  { tab: 'chat', label: 'Assist', icon: 'chat' },
];

export function NavRail({ panelOpen, onTogglePanel }: NavRailProps) {
  const { panel, setPanel } = useAppState();

  const handleClick = (tab: PanelTab) => {
    if (panelOpen && panel === tab) {
      // Clicking the already-active tab toggles the panel closed
      onTogglePanel(false);
    } else {
      setPanel(tab);
      onTogglePanel(true);
    }
  };

  return (
    <nav className="nav-rail">
      <div className="nav-brand" title="ParkVisionSaathi">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 22s-8-4.5-8-11.8A8 8 0 0 1 12 2a8 8 0 0 1 8 8.2c0 7.3-8 11.8-8 11.8z" />
          <circle cx="12" cy="10" r="3" />
        </svg>
      </div>
      <div className="nav-items">
        {ITEMS.map((it) => (
          <button
            key={it.tab}
            className={`nav-item ${panelOpen && panel === it.tab ? 'active' : ''}`}
            title={it.label}
            onClick={() => handleClick(it.tab)}
          >
            {ICONS[it.icon]}
            <span>{it.label}</span>
          </button>
        ))}
      </div>
    </nav>
  );
}

