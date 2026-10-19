import { useEffect, useMemo, useRef } from 'react';

import { type LogLine, logLines } from '../lib/logLines';
import { useConnection } from '../store/connection';

const TONE_CLASS: Record<LogLine['tone'], string> = {
  policy: 'text-term-accent',
  shock: 'text-term-down',
  projection: 'text-term-amber',
  info: 'text-term-muted',
  warning: 'text-term-down',
  ok: 'text-term-up',
  fail: 'text-term-down',
  system: 'text-term-muted',
};

/** Shocks, policy actions and command results, newest at the bottom (simulated time). */
export function EventLog() {
  const log = useConnection((s) => s.log);
  const lines = useMemo(() => log.flatMap(logLines), [log]);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [lines]);

  return (
    <section aria-label="event log" className="flex min-h-0 flex-col border-t border-term-line">
      <h2 className="border-b border-term-line bg-term-panel px-3 py-0.5 text-xs tracking-widest text-term-muted">
        EVENT LOG · SIM TIME UTC
      </h2>
      <ol ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-1 text-xs leading-5">
        {lines.length === 0 && <li className="text-term-muted">No events yet.</li>}
        {lines.map((line) => (
          <li key={line.key} className="flex gap-3">
            <time className="shrink-0 text-term-muted">{line.time}</time>
            <span className={`w-16 shrink-0 uppercase ${TONE_CLASS[line.tone]}`}>{line.label}</span>
            <span className="text-term-text">{line.text}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
