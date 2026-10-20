import { useCallback, useEffect } from 'react';

import { useHealth } from '../api/useHealth';
import { useCommands, useSimStatus } from '../api/useSim';
import { CommandBar } from '../components/CommandBar';
import { EventLog } from '../components/EventLog';
import { StatusStrip } from '../components/StatusStrip';
import { TickerTape } from '../components/TickerTape';
import { PanelGrid } from '../panels/PanelGrid';
import { SLOT_COUNT, STARTUP_COMMANDS, useMarket } from '../store/market';
import { send, startSession } from '../ws/session';

const NO_QUALITY: readonly string[] = [];

export function App() {
  const health = useHealth();
  const sim = useSimStatus();
  const commands = useCommands();
  const focus = useMarket((s) => s.focus);

  useEffect(() => {
    const stop = startSession();
    // Fill the four slots: the sends queue until the socket opens.
    for (const text of STARTUP_COMMANDS) send({ op: 'command', text });
    return stop;
  }, []);

  // Alt+1..4 (or Ctrl+1..4 where the browser does not take it for tabs) focuses a panel.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.altKey || event.ctrlKey)) return;
      const n = Number(event.key);
      if (Number.isInteger(n) && n >= 1 && n <= SLOT_COUNT) {
        event.preventDefault();
        focus(n - 1);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  }, [focus]);

  const submit = useCallback((text: string) => {
    send({ op: 'command', text });
  }, []);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b border-term-line px-3 py-1.5">
        <h1 className="text-sm font-semibold tracking-[0.25em] text-term-amber">
          SOVEREIGN<span className="text-term-text">DESK</span>
        </h1>
        <CommandBar onSubmit={submit} commands={commands} />
      </header>
      <StatusStrip health={health} sim={sim} />
      <TickerTape />
      <main className="grid min-h-0 min-w-0 flex-1 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)_minmax(6rem,20%)]">
        <div className="min-h-0 min-w-0 p-1">
          <PanelGrid
            quality={{
              us: sim?.input_quality ?? NO_QUALITY,
              india: sim?.india.input_quality ?? NO_QUALITY,
            }}
          />
        </div>
        <EventLog />
      </main>
    </div>
  );
}
