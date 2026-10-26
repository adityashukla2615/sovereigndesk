import { useCallback, useEffect } from 'react';

import { useHealth } from '../api/useHealth';
import { useCommands, useSimStatus } from '../api/useSim';
import { CommandBar } from '../components/CommandBar';
import { EventLog } from '../components/EventLog';
import { StatusStrip } from '../components/StatusStrip';
import { TickerTape } from '../components/TickerTape';
import { REPO_URL, STATIC_DEMO } from '../lib/staticDemo';
import { PanelGrid } from '../panels/PanelGrid';
import { DEFAULT_LAYOUT, lastLayout, layoutOf, rememberLayout, useLayout } from '../store/layouts';
import { SLOT_COUNT, useMarket } from '../store/market';
import { send, startSession } from '../ws/session';
import { restoreLayout } from './layoutCommand';

const NO_QUALITY: readonly string[] = [];

/** Slots sit in a 2 × 2 grid: 1 and 2 on top, 3 and 4 below. */
const NEIGHBOUR: Record<string, readonly number[]> = {
  ArrowLeft: [1, 0, 3, 2],
  ArrowRight: [1, 0, 3, 2],
  ArrowUp: [2, 3, 0, 1],
  ArrowDown: [2, 3, 0, 1],
};

/** Focus a slot in the store and move the keyboard into it. */
function focusSlot(index: number): void {
  useMarket.getState().focus(index);
  document.querySelector<HTMLElement>(`[data-slot="${String(index)}"]`)?.focus();
}

export function App() {
  const health = useHealth();
  const sim = useSimStatus();
  const commands = useCommands();

  useEffect(() => {
    const stop = startSession();
    // Reopen the last layout, else the default; the sends queue until the socket opens.
    restoreLayout(lastLayout() ?? DEFAULT_LAYOUT, send);
    const remember = () => {
      rememberLayout(layoutOf(useMarket.getState().slots, useLayout.getState().sizes));
    };
    const stopMarket = useMarket.subscribe(remember);
    const stopLayout = useLayout.subscribe(remember);
    return () => {
      stopMarket();
      stopLayout();
      stop();
    };
  }, []);

  // Alt+1..4 (or Ctrl+1..4 where the browser does not take it for tabs) focuses a panel, Alt+arrows
  // move between panels, Alt+Enter shows the focused one alone, F1 explains it, Alt+T teaches.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const { focused, slots } = useMarket.getState();
      if (event.key === 'F1') {
        event.preventDefault();
        const panel = slots[focused]?.panel;
        if (panel) send({ op: 'command', text: `HELP ${panel}` });
        return;
      }
      if (!(event.altKey || event.ctrlKey)) return;
      const n = Number(event.key);
      if (Number.isInteger(n) && n >= 1 && n <= SLOT_COUNT) {
        event.preventDefault();
        focusSlot(n - 1);
        return;
      }
      if (!event.altKey || event.ctrlKey) return;
      const next = NEIGHBOUR[event.key]?.[focused];
      if (next !== undefined) {
        event.preventDefault();
        if (useLayout.getState().maximized !== null) useLayout.getState().toggleMaximized(focused);
        focusSlot(next);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        useLayout.getState().toggleMaximized(focused);
      } else if (event.key.toLowerCase() === 't') {
        event.preventDefault();
        send({ op: 'command', text: 'TEACH' });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  }, []);

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
      {STATIC_DEMO && (
        <p role="note" className="border-b border-term-amber bg-term-panel px-3 py-1 text-[11px] text-term-text">
          <span className="text-term-amber">STATIC DEMO.</span> Every reply and tick here was recorded from the
          real simulator on the committed data (19 Oct 2026), and plays back in your browser: try{' '}
          <span className="text-term-amber">PY 10Y · QT 95B · SHOCK JP 200B 10D LONG · SHOCK FED 50BP · REPLAY
          TAPER2013 · TAXCAL · MPC · HELP</span>, and RESET to start over. For the live simulator, run it locally:{' '}
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="text-term-accent underline">
            github.com/adityashukla2615/sovereigndesk
          </a>
          .
        </p>
      )}
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
