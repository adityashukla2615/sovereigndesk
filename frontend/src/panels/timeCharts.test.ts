import { describe, expect, it } from 'vitest';

import type { Palette } from '../lib/palette';
import { CALL_DATA, DEBT_DATA, TAXCAL_DATA } from '../test/terminalData';
import { taxHeatmapOption, taxWindows } from './taxcalOptions';
import { debtChart, roundsChart, taxChart } from './timeCharts';

const P: Palette = {
  bg: '#000',
  panel: '#111',
  line: '#222',
  amber: '#fa0',
  text: '#eee',
  muted: '#777',
  up: '#0f0',
  down: '#f00',
  accent: '#0af',
};

describe('time chart builders', () => {
  it('draws the call rounds at Mumbai wall-clock times inside the corridor', () => {
    const chart = roundsChart(CALL_DATA, { sdf: 0.0525, repo: 0.055, msf: 0.0575 }, P);
    expect(chart.dates).toEqual(['2026-10-20T09:15', '2026-10-20T09:30', '2026-10-20T09:45']);
    expect(chart.lines.map((l) => l.name)).toEqual(['Round rate', 'MSF', 'Repo', 'SDF']);
    expect(chart.lines[1]?.values).toEqual([5.75, 5.75, 5.75]);
  });

  it('runs the tax cycle on every calendar day, simulated then projected, with RBI marked', () => {
    const chart = taxChart(TAXCAL_DATA, P);
    expect(chart.dates).toEqual(['2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22']);
    const [surplus, government] = chart.lines;
    expect(surplus?.values).toEqual([1.9, 1.85873, 1.68251, -0.2]); // ₹ lakh crore
    expect(government?.values).toEqual([0, 0, 0.17622, 0.35244]);
    expect(chart.markers.map((m) => [m.date, m.text])).toEqual([
      ['2026-10-19', 'VRRR'],
      ['2026-10-20', 'today'],
      ['2026-10-21', 'VRRR?'],
      ['2026-10-22', 'VRR?'],
    ]);
  });

  it('groups the tax days ahead into windows', () => {
    expect(taxWindows(TAXCAL_DATA)).toEqual([
      { kind: 'GST', first: '2026-10-20', last: '2026-10-21', drain: 35_244 },
      { kind: 'Advance tax', first: '2026-12-13', last: '2026-12-14', drain: 51_370 },
      { kind: 'GST', first: '2026-12-18', last: '2026-12-18', drain: 17_622 },
    ]);
  });

  it('maps the year to the simulated today, real days first, advance-tax days marked', () => {
    const option = taxHeatmapOption(TAXCAL_DATA, P) as {
      calendar: { range: string[] };
      series: { data: [string, number][] }[];
    };
    expect(option.calendar.range).toEqual(['2025-10-21', '2026-10-20']);
    expect(option.series[0]?.data).toEqual([
      ['2026-09-14', -4],
      ['2026-09-15', 18],
      ['2026-09-16', 21],
      ['2026-10-19', -21],
    ]);
    expect(option.series[1]?.data.map(([d]) => d)).toEqual(['2025-12-15', '2026-03-15', '2026-06-15', '2026-09-15']);
  });

  it('shows the interest bill in dollars or as a share of GDP or receipts', () => {
    expect(debtChart(DEBT_DATA, 'usd', P).lines[0]?.values[11]).toBe(1033);
    expect(debtChart(DEBT_DATA, 'gdp', P).lines[0]?.values[0]).toBeCloseTo(3.15);
    expect(debtChart(DEBT_DATA, 'receipts', P).digits).toBe(1);
  });
});
