import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ConnectionStatus } from './client';
import type { Envelope } from './protocol';
import { type DemoSession, StaticClient } from './staticClient';

const frame = (n: number) => ({ us: { effr: n }, india: { wacr: n } });

const SESSION: DemoSession = {
  recorded: '2026-10-26T08:00:00+00:00',
  start: '2026-10-27T04:00:00+00:00',
  history: [{ code: 'ANCHOR', text: 'anchored' }],
  baseline: [frame(1), frame(2)],
  replies: {
    FED: { reply: { ok: true, code: 'FED', message: 'baseline FED', panel: 'FED', data: {} }, events: [] },
    'PY 10Y': { reply: { ok: true, code: 'PY', message: 'py', panel: 'PY', data: {} }, events: [] },
  },
  actions: {
    'HIKE 25BP': {
      reply: { ok: true, code: 'HIKE', message: 'FOMC hike', panel: 'FED', data: null },
      events: [{ code: 'HIKE', text: 'FOMC hike +25 bp' }],
      tape: [frame(9)],
      after: { FED: { ok: true, code: 'FED', message: 'FED after the hike', panel: 'FED', data: {} } },
    },
  },
  reset: { reply: { ok: true, code: 'RESET', message: 'reset', panel: null, data: { refresh: true } }, events: [] },
};

describe('static demo transport', () => {
  let messages: Envelope[];
  let statuses: ConnectionStatus[];
  let client: StaticClient;

  beforeEach(async () => {
    vi.useFakeTimers();
    messages = [];
    statuses = [];
    client = new StaticClient({
      onMessage: (m) => messages.push(m),
      onStatus: (s) => statuses.push(s),
      load: () => Promise.resolve(SESSION),
      frameMs: 1000,
    });
    client.send({ op: 'command', text: 'py  10y' }); // queued until the recording loads
    client.start();
    await Promise.resolve(); // the recording "loads"
    await Promise.resolve();
  });

  afterEach(() => {
    client.stop();
    vi.useRealTimers();
  });

  const replies = () => messages.filter((m) => m.topic === 'command').map((m) => m.data as Record<string, unknown>);
  const ticks = () => messages.filter((m) => m.topic === 'us.tick').map((m) => (m.data as { effr: number }).effr);

  it('opens on the recording, answers queued commands and plays the tape in a loop', () => {
    expect(statuses).toEqual(['connecting', 'open']);
    expect(messages[0]).toMatchObject({ topic: 'events', data: SESSION.history });
    expect(replies()[0]).toMatchObject({ message: 'py', command: 'PY 10Y' });
    vi.advanceTimersByTime(2000);
    expect(ticks()).toEqual([1, 2, 1]);
  });

  it('switches to a command’s own tape and replies, and RESET goes back', () => {
    client.send({ op: 'command', text: 'HIKE 25BP' });
    expect(messages.some((m) => m.topic === 'events' && (m.data as { text: string }).text === 'FOMC hike +25 bp')).toBe(true);
    expect(ticks().at(-1)).toBe(9);
    client.send({ op: 'command', text: 'FED' });
    expect(replies().at(-1)?.message).toBe('FED after the hike');
    client.send({ op: 'command', text: 'RESET' });
    client.send({ op: 'command', text: 'FED' });
    expect(replies().at(-1)?.message).toBe('baseline FED');
    expect(ticks().at(-1)).toBe(1);
  });

  it('says what it cannot do instead of pretending', () => {
    client.send({ op: 'command', text: 'HIKE 75BP' });
    expect(replies().at(-1)).toMatchObject({ ok: false });
    expect(String(replies().at(-1)?.message)).toContain('Try HIKE 25BP');
    client.send({ op: 'command', text: 'SAVE X' });
    expect(String(replies().at(-1)?.message)).toContain('needs the live terminal');
    client.send({ op: 'command', text: 'NOPE' });
    expect(String(replies().at(-1)?.message)).toBe('Unknown function NOPE in this demo. Type HELP.');
    client.send({ op: 'command', text: 'layout save rates' });
    expect(replies().at(-1)).toMatchObject({ ok: true, data: { layout: { action: 'save', name: 'RATES' } } });
    client.send({ op: 'command', text: 'EXPORT PNG' });
    expect(replies().at(-1)).toMatchObject({ ok: true, data: { export: { format: 'png' } } });
    client.send({ op: 'command', text: 'PAUSE' });
    const seen = ticks().length;
    vi.advanceTimersByTime(5000);
    expect(ticks()).toHaveLength(seen);
  });
});
