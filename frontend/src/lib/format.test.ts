import { describe, expect, it } from 'vitest';

import { suggest } from './suggest';
import { bp, direction, inrCr, pct, usdBn } from './format';
import { tickerQuotes } from './ticker';
import { IN_TICK, US_TICK } from '../test/marketData';

describe('formats', () => {
  it('formats rates, changes and amounts like the backend narratives', () => {
    expect(pct(0.0525)).toBe('5.25%');
    expect(pct(null)).toBe('—');
    expect(bp(0.0018)).toBe('+18 bp');
    expect(bp(-0.0025)).toBe('-25 bp');
    expect(bp(0.00002)).toBe('+0.2 bp');
    expect(inrCr(185_873)).toBe('₹1.86 lakh cr');
    expect(inrCr(34_528)).toBe('₹34,528 cr');
    expect(usdBn(2980)).toBe('$2.98tn');
    expect(usdBn(95)).toBe('$95bn');
    expect(usdBn(1.5)).toBe('$1.5bn');
    expect(usdBn(-2280)).toBe('−$2.28tn');
    expect(inrCr(-50_000)).toBe('−₹50,000 cr');
    expect(direction(2, 1)).toBe(1);
    expect(direction(1, 2)).toBe(-1);
    expect(direction(1, null)).toBe(0);
  });
});

describe('ticker', () => {
  it('quotes both markets and colours moves against the previous tick', () => {
    const before = { ...US_TICK, curve: { ...US_TICK.curve, '10Y': 0.0405 } };
    const quotes = tickerQuotes(US_TICK, before, IN_TICK, null);
    const byLabel = Object.fromEntries(quotes.map((q) => [q.label, q]));
    expect(byLabel['UST 10Y']).toEqual({ label: 'UST 10Y', text: '4.100%', move: 1 });
    expect(byLabel['2s10s']?.text).toBe('+58 bp');
    expect(byLabel.WACR).toEqual({ label: 'WACR', text: '5.28%', move: 0 });
    expect(byLabel.SURPLUS?.text).toBe('0.67% NDTL');
    expect(tickerQuotes(null, null, null, null)).toEqual([]);
  });
});

describe('suggest', () => {
  const commands = [
    { code: 'QT', usage: 'QT 95B', summary: '', group: 'US', available: true, available_in: null },
    { code: 'QUIT', usage: 'QUIT', summary: '', group: 'SYS', available: false, available_in: 'Phase 12' },
    { code: 'PY', usage: 'PY [tenor]', summary: '', group: 'US', available: true, available_in: null },
  ];

  it('matches the code prefix only while the code is being typed', () => {
    expect(suggest(commands, 'q').map((c) => c.code)).toEqual(['QT', 'QUIT']);
    expect(suggest(commands, 'QT 95B')).toEqual([]);
    expect(suggest(commands, '')).toEqual([]);
  });
});

describe('corridor helpers', () => {
  it('merges marks at the same rate and formats simulated time by zone', async () => {
    const { mergeMarks, simClock } = await import('./corridor');
    const merged = mergeMarks([
      { label: 'LOW', rate: 0.0375 },
      { label: 'RRP', rate: 0.0375 },
      { label: 'IORB', rate: 0.039 },
    ]);
    expect(merged.map((m) => m.label)).toEqual(['LOW · RRP', 'IORB']);
    expect(simClock('2026-10-20T05:12:00Z', 'Asia/Kolkata')).toBe('Tue 20 Oct 10:42');
    expect(simClock('nonsense', 'Asia/Kolkata')).toBe('—');
  });
});
