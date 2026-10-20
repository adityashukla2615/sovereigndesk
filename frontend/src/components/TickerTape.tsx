import { useShallow } from 'zustand/react/shallow';

import { tickerQuotes } from '../lib/ticker';
import { useMarket } from '../store/market';

const MOVE_CLASS = { 1: 'text-term-up', 0: 'text-term-text', '-1': 'text-term-down' } as const;
const ARROW = { 1: '▲', 0: ' ', '-1': '▼' } as const;

/** Key US and India quotes; a value flashes when it changes. */
export function TickerTape() {
  const ticks = useMarket(
    useShallow((s) => ({ us: s.us, usBefore: s.usBefore, india: s.india, indiaBefore: s.indiaBefore })),
  );
  const quotes = tickerQuotes(ticks.us, ticks.usBefore, ticks.india, ticks.indiaBefore);
  return (
    <div
      role="marquee"
      aria-label="ticker"
      className="flex gap-5 overflow-x-auto border-b border-term-line px-3 py-1 text-xs whitespace-nowrap"
    >
      {quotes.length === 0 && <span className="text-term-muted">Waiting for market ticks…</span>}
      {quotes.map((q) => (
        <span key={q.label} className="flex gap-1.5">
          <span className="text-term-muted">{q.label}</span>
          <span key={q.text} className={`animate-[tick_0.8s_ease-out] ${MOVE_CLASS[q.move]}`}>
            {q.text}
            <span aria-hidden="true" className="ml-0.5 text-[9px]">
              {ARROW[q.move]}
            </span>
          </span>
          {q.stale && <span className="text-[10px] text-term-down">{q.stale}</span>}
        </span>
      ))}
    </div>
  );
}
