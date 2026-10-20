import { describe, expect, it } from 'vitest';

import { envelope } from '../test/fakeSocket';
import { logLines } from './logLines';

const SHOCK = {
  sim_time: '2026-10-19T14:05:00+00:00',
  kind: 'shock',
  code: 'SHOCK',
  text: 'Japan sells $200bn of Treasuries (LONG) over 10 days → …',
  data: {},
};

describe('logLines', () => {
  it('expands the events snapshot and single events, in simulated time', () => {
    const snapshot = logLines(envelope('events', 1, [SHOCK, { ...SHOCK, kind: 'policy', code: 'HIKE' }]));
    expect(snapshot.map((l) => [l.label, l.tone, l.time])).toEqual([
      ['SHOCK', 'shock', '14:05:00'],
      ['HIKE', 'policy', '14:05:00'],
    ]);
    expect(new Set(snapshot.map((l) => l.key)).size).toBe(2);
    expect(logLines(envelope('events', 2, SHOCK))).toHaveLength(1);
  });

  it('shows command results as ok or failed', () => {
    const ok = logLines(envelope('command', 3, { ok: true, code: 'QT', message: 'QT $95bn/month' }));
    const bad = logLines(envelope('command', 4, { ok: false, code: 'UTS', message: 'Unknown function' }));
    expect(ok[0]).toMatchObject({ label: 'QT', tone: 'ok', text: 'QT $95bn/month' });
    expect(bad[0]).toMatchObject({ tone: 'fail' });
  });

  it('stamps replies in simulated time and leaves narrated ones to their event', () => {
    const reply = { ok: true, code: 'PY', message: '10Y par bond', sim_time: '2026-10-20T05:01:02+00:00' };
    expect(logLines(envelope('command', 5, reply))[0]?.time).toBe('05:01:02');
    expect(logLines(envelope('command', 6, { ...reply, code: 'HIKE', narrated: true }))).toEqual([]);
    expect(logLines(envelope('command', 7, { ...reply, ok: false, narrated: true }))).toHaveLength(1);
  });

  it('ignores ticks, acknowledgements and malformed data', () => {
    expect(logLines(envelope('us.tick', 5, { curve: {} }))).toEqual([]);
    expect(logLines(envelope('status', 6, { subscribed: ['events'] }))).toEqual([]);
    expect(logLines(envelope('events', 7, { nonsense: true }))).toEqual([]);
  });
});
