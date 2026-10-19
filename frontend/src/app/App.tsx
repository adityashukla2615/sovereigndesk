import { useCallback, useEffect } from 'react';

import { useHealth } from '../api/useHealth';
import { CommandBar } from '../components/CommandBar';
import { EventLog } from '../components/EventLog';
import { StatusStrip } from '../components/StatusStrip';
import { send, startSession } from '../ws/session';

function ShellPanel() {
  return (
    <section aria-label="welcome" className="min-h-0 overflow-y-auto p-4 text-sm leading-6">
      <h2 className="mb-2 text-xs tracking-widest text-term-muted">SHELL · PHASE 1</h2>
      <p className="max-w-3xl text-term-text">
        The terminal is wired end to end: this page talks to FastAPI over REST{' '}
        <code className="text-term-amber">/api/health</code> and a WebSocket{' '}
        <code className="text-term-amber">/ws</code>. Type anything into the command bar and the
        backend echoes it into the event log.
      </p>
      <p className="mt-2 max-w-3xl text-term-muted">
        Market panels (PY price–yield, FED/QT shock, WACR corridor) arrive with the MVP.
      </p>
    </section>
  );
}

export function App() {
  const health = useHealth();
  useEffect(() => startSession(), []);
  const submit = useCallback((text: string) => {
    send({ op: 'command', text });
  }, []);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b border-term-line px-3 py-1.5">
        <h1 className="text-sm font-semibold tracking-[0.25em] text-term-amber">
          SOVEREIGN<span className="text-term-text">DESK</span>
        </h1>
        <CommandBar onSubmit={submit} />
      </header>
      <StatusStrip health={health} />
      <main className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(8rem,35%)]">
        <ShellPanel />
        <EventLog />
      </main>
    </div>
  );
}
