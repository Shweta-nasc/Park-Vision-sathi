import { useRef, useState } from 'react';
import { useExplain } from '@/hooks/queries';
import { useAppState } from '@/state/AppState';

interface Msg { role: 'user' | 'assistant'; text: string; loading?: boolean }

const PROMPTS = [
  'Why is this area high risk?',
  'Suggest patrol strategy for this shift',
  'How many officers are needed?',
  'Summarize priority areas',
];

/**
 * AI assistant. "Why / explain / risk" questions about a selected zone hit the
 * real POST /explain (LLM + cache). Other questions use a fast rule-based reply.
 */
export function ChatPanel() {
  const { selectedZone, hour } = useAppState();
  const explain = useExplain();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const scrollDown = () => requestAnimationFrame(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  });

  const ruleBased = (p: string): string | null => {
    const q = p.toLowerCase();
    if (q.includes('strategy') || q.includes('patrol')) {
      return `Strategic patrol summary for hour ${hour}:00:\n• Prioritise the top hotspots shown on the map.\n• Deploy more units where patrol probability is highest (Game tab).\n• Watch spillover zones — enforcing here pushes violations to neighbours.`;
    }
    if (q.includes('officer') || q.includes('force') || q.includes('needed')) {
      return `Force guidance: HIGH zones need ~3 units, MEDIUM ~2, LOW ~1. Open a zone's detail for its exact recommendation, or run the Simulation tab to optimise team allocation.`;
    }
    if (q.includes('summary') || q.includes('priority')) {
      return `Open the Priority Areas strip below the map for the ranked list. High-priority areas are badged red. Select one to see its full impact breakdown.`;
    }
    return null;
  };

  const send = async (text: string) => {
    if (!text.trim()) return;
    setMessages((m) => [...m, { role: 'user', text }]);
    setInput('');
    scrollDown();

    const rb = ruleBased(text);
    const wantsExplain = /why|explain|risk|congest/i.test(text);

    if (selectedZone && wantsExplain) {
      setMessages((m) => [...m, { role: 'assistant', text: 'Analysing zone…', loading: true }]);
      scrollDown();
      try {
        const res = await explain.mutateAsync({ h3_id: selectedZone.h3_id, hour });
        const tag = res.source === 'gemini' ? ' (AI)' : res.is_cached ? ' (cached)' : '';
        setMessages((m) => [
          ...m.slice(0, -1),
          { role: 'assistant', text: `${res.explanation}${tag}` },
        ]);
      } catch {
        setMessages((m) => [
          ...m.slice(0, -1),
          { role: 'assistant', text: 'Could not reach the explanation service. Try again.' },
        ]);
      }
      scrollDown();
      return;
    }

    const reply =
      rb ??
      (wantsExplain
        ? 'Select a zone on the map first, then ask me why it is high risk.'
        : 'I can help with patrol strategy, force needs, priority summaries, and zone risk explanations. Select a zone to dive deeper.');
    setMessages((m) => [...m, { role: 'assistant', text: reply }]);
    scrollDown();
  };

  return (
    <div className="chat-panel">
      <div className="chat-messages" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-welcome">
            <p><strong>Patrol Assistant</strong></p>
            <p className="text-muted">Ask about priority areas, patrol strategy, or why a zone is high risk.</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            {m.loading ? <span className="typing">●●●</span> : m.text}
          </div>
        ))}
      </div>
      <div className="chat-prompts">
        {PROMPTS.map((p) => (
          <button key={p} className="prompt-chip" onClick={() => send(p)}>
            {p}
          </button>
        ))}
      </div>
      <div className="chat-input-area">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send(input)}
          placeholder="Ask the patrol assistant..."
          autoComplete="off"
        />
        <button className="chat-send-btn" onClick={() => send(input)} title="Send">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>
  );
}
