import { useEffect, useRef } from 'react';

import { useConnection } from '../store/connection';
import type { Envelope } from '../ws/protocol';

const TOPIC_CLASS: Record<string, string> = {
  echo: 'text-term-amber',
  status: 'text-term-accent',
  error: 'text-term-down',
  pong: 'text-term-muted',
};

function summarize({ topic, data }: Envelope): string {
  if (topic === 'echo' && typeof data === 'object' && data !== null && 'text' in data) {
    return String(data.text);
  }
  return JSON.stringify(data);
}

export function EventLog() {
  const log = useConnection((s) => s.log);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [log]);

  return (
    <section aria-label="event log" className="flex min-h-0 flex-col border-t border-term-line">
      <h2 className="border-b border-term-line bg-term-panel px-3 py-0.5 text-xs tracking-widest text-term-muted">
        EVENT LOG · UTC
      </h2>
      <ol ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-1 text-xs leading-5">
        {log.length === 0 && <li className="text-term-muted">No messages yet.</li>}
        {log.map((message) => (
          <li key={`${message.ts}-${String(message.seq)}`} className="flex gap-3">
            <time dateTime={message.ts} className="shrink-0 text-term-muted">
              {message.ts.slice(11, 19)}
            </time>
            <span className={`w-14 shrink-0 uppercase ${TOPIC_CLASS[message.topic] ?? 'text-term-text'}`}>
              {message.topic}
            </span>
            <span className="truncate text-term-text">{summarize(message)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
