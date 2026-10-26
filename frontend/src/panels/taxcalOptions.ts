/** The TAXCAL calendar heatmap and tax windows: pure functions of the panel data. */

import type { ChartOption } from '../components/Chart';
import type { Palette } from '../lib/palette';
import type { TaxcalPanelData } from '../market/types';
import { base } from './options';

const QUARTER_MONTHS = new Set([3, 6, 9, 12]);
const ADVANCE_TAX_DAY = 15;
const LIMIT_BP = 40;

function shifted(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** WACR − repo by day over the year to the simulated today, real days then simulated ones, with
 * the advance-tax due dates marked. Green is surplus (below repo), red tight (above). */
export function taxHeatmapOption(panel: TaxcalPanelData, p: Palette): ChartOption {
  const end = panel.now.date;
  const start = shifted(end, -364);
  const cells = new Map<string, number>();
  for (const d of panel.real) if (d.date >= start && d.date <= end) cells.set(d.date, d.spread * 1e4);
  for (const d of panel.simulated) {
    if (d.spread !== null && d.date >= start && d.date <= end) cells.set(d.date, d.spread * 1e4);
  }
  const due: string[] = [];
  for (let day = start; day <= end; day = shifted(day, 1)) {
    const month = Number(day.slice(5, 7));
    if (QUARTER_MONTHS.has(month) && Number(day.slice(8, 10)) === ADVANCE_TAX_DAY) due.push(day);
  }
  return {
    ...base(p),
    legend: { show: false },
    tooltip: {
      trigger: 'item',
      backgroundColor: p.panel,
      borderColor: p.line,
      textStyle: { color: p.text, fontSize: 11 },
    },
    visualMap: {
      type: 'continuous',
      seriesIndex: 0,
      min: -LIMIT_BP,
      max: LIMIT_BP,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemHeight: 120,
      itemWidth: 8,
      text: [`tight +${String(LIMIT_BP)} bp`, `surplus −${String(LIMIT_BP)} bp`],
      textStyle: { color: p.muted, fontSize: 9 },
      inRange: { color: [p.up, p.panel, p.down] },
    },
    calendar: {
      range: [start, end],
      top: 18,
      left: 22,
      right: 6,
      bottom: 34,
      cellSize: ['auto', 'auto'],
      splitLine: { lineStyle: { color: p.line } },
      itemStyle: { color: p.bg, borderColor: p.line, borderWidth: 0.5 },
      yearLabel: { show: false },
      monthLabel: { color: p.muted, fontSize: 9 },
      dayLabel: { color: p.muted, fontSize: 8, firstDay: 1, nameMap: ['S', 'M', 'T', 'W', 'T', 'F', 'S'] },
    },
    series: [
      {
        name: 'WACR − repo (bp)',
        type: 'heatmap',
        coordinateSystem: 'calendar',
        data: [...cells].map(([date, value]) => [date, Math.round(value)]),
      },
      {
        name: 'Advance tax due',
        type: 'scatter',
        coordinateSystem: 'calendar',
        symbol: 'circle',
        symbolSize: 4,
        itemStyle: { color: p.amber },
        data: due.map((date) => [date, 1]),
      },
    ],
  };
}

export interface TaxWindow {
  kind: 'Advance tax' | 'GST';
  first: string;
  last: string;
  drain: number;
}

/** The days ahead grouped into tax windows: advance tax around the 15th of Mar/Jun/Sep/Dec,
 * GST around the 20th of every month. */
export function taxWindows(panel: TaxcalPanelData): TaxWindow[] {
  const windows: TaxWindow[] = [];
  for (const d of panel.tax_days) {
    const month = Number(d.date.slice(5, 7));
    const day = Number(d.date.slice(8, 10));
    const kind = QUARTER_MONTHS.has(month) && day <= 17 ? 'Advance tax' : 'GST';
    const open = windows[windows.length - 1];
    if (open?.kind === kind && shifted(open.last, 1) === d.date) {
      open.last = d.date;
      open.drain += d.drain;
    } else {
      windows.push({ kind, first: d.date, last: d.date, drain: d.drain });
    }
  }
  return windows;
}
