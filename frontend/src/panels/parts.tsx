import type { ReactNode } from 'react';

import { useMarket } from '../store/market';
import { TEACH } from './teach';

/** A label and value, the panels' basic reading. */
export function Stat({ label, children, tone }: { label: string; children: ReactNode; tone?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] tracking-wider text-term-muted">{label}</span>
      <span className={`text-sm ${tone ?? 'text-term-text'}`}>{children}</span>
    </div>
  );
}

export function StatRow({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap gap-x-5 gap-y-1">{children}</div>;
}

/** The economics behind a panel, visible in teach mode. */
export function TeachNote({ code }: { code: string }) {
  const teach = useMarket((s) => s.teach);
  const text = TEACH[code];
  if (!teach || !text) return null;
  return (
    <aside
      aria-label={`teach note for ${code}`}
      className="border-l-2 border-term-accent bg-term-panel px-2 py-1 text-[11px] leading-4 text-term-text"
    >
      {text}
    </aside>
  );
}

export function Waiting({ what }: { what: string }) {
  return <p className="p-2 text-xs text-term-muted">Waiting for {what}…</p>;
}
