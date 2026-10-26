/** What the CALL and TAXCAL time charts draw: pure functions of their panel data. */

import type { TimeChartData } from '../components/TimeChart';
import type { Palette } from '../lib/palette';
import type { CallPanelData, DebtPanelData, TaxcalPanelData } from '../market/types';

/** Today's clearing rounds against RBI's corridor, in per cent, at Mumbai's wall-clock times. */
export function roundsChart(
  panel: CallPanelData,
  corridor: { sdf: number; repo: number; msf: number },
  p: Palette,
): TimeChartData {
  const day = panel.time.slice(0, 10);
  const dates = panel.rounds.map((r) => `${day}T${r.time}`);
  const flat = (rate: number) => dates.map(() => rate * 100);
  return {
    dates,
    lines: [
      { name: 'Round rate', colour: p.amber, values: panel.rounds.map((r) => r.rate * 100) },
      { name: 'MSF', colour: p.down, dashed: true, values: flat(corridor.msf) },
      { name: 'Repo', colour: p.muted, dashed: true, values: flat(corridor.repo) },
      { name: 'SDF', colour: p.up, dashed: true, values: flat(corridor.sdf) },
    ],
    markers: [],
    digits: 2,
  };
}

function* calendarDays(first: string, last: string): Generator<string> {
  const day = new Date(`${first}T00:00:00Z`);
  const end = new Date(`${last}T00:00:00Z`);
  while (day <= end) {
    yield day.toISOString().slice(0, 10);
    day.setUTCDate(day.getUTCDate() + 1);
  }
}

/** The system's surplus and the government's tax balance at RBI: the simulated days so far,
 * then the days ahead from tax flows alone. Marked: RBI's auctions on simulated days, and the
 * days ahead where its fitted reaction makes an auction more likely than not. */
export function taxChart(panel: TaxcalPanelData, p: Palette): TimeChartData {
  const known = new Map<string, { surplus: number; government: number }>();
  const marks = new Map<string, string>();
  for (const d of panel.simulated) {
    known.set(d.date, d);
    if (d.vrr > 0) marks.set(d.date, 'VRR');
    else if (d.vrrr > 0) marks.set(d.date, 'VRRR');
  }
  known.set(panel.now.date, panel.now);
  for (const d of panel.projection) {
    known.set(d.date, d);
    if (d.p_vrr >= 0.5) marks.set(d.date, 'VRR?');
    else if (d.p_vrrr >= 0.5) marks.set(d.date, 'VRRR?');
  }
  const ordered = [...known.keys()].sort();
  const first = ordered[0] ?? panel.now.date;
  const last = ordered[ordered.length - 1] ?? panel.now.date;
  const dates = [...calendarDays(first, last)];
  const value = (date: string, key: 'surplus' | 'government') => {
    const v = known.get(date)?.[key];
    return v === undefined ? null : v / 100_000; // ₹ lakh crore
  };
  return {
    dates,
    lines: [
      { name: 'System surplus', colour: p.amber, values: dates.map((d) => value(d, 'surplus')) },
      {
        name: 'Government’s tax balance at RBI',
        colour: p.accent,
        values: dates.map((d) => value(d, 'government')),
      },
    ],
    markers: [
      { date: panel.now.date, text: 'today' },
      ...[...marks].map(([date, text]) => ({ date, text })),
    ].sort((a, b) => a.date.localeCompare(b.date)),
    digits: 2,
  };
}

export type DebtMeasure = 'usd' | 'gdp' | 'receipts';

export const DEBT_MEASURES: Record<DebtMeasure, { label: string; unit: string; digits: number }> = {
  usd: { label: '$BN A YEAR', unit: '$bn a year', digits: 0 },
  gdp: { label: '% OF GDP', unit: '% of GDP', digits: 2 },
  receipts: { label: '% OF RECEIPTS', unit: '% of federal receipts', digits: 1 },
};

/** Interest on marketable debt month by month, on today's curve and on the simulated one. */
export function debtChart(panel: DebtPanelData, measure: DebtMeasure, p: Palette): TimeChartData {
  const [base, shocked] =
    measure === 'usd'
      ? [panel.baseline_interest, panel.shocked_interest]
      : measure === 'gdp'
        ? [panel.baseline_to_gdp.map((v) => v * 100), panel.shocked_to_gdp.map((v) => v * 100)]
        : [panel.baseline_to_receipts.map((v) => v * 100), panel.shocked_to_receipts.map((v) => v * 100)];
  return {
    dates: panel.months,
    lines: [
      { name: 'On the simulated curve', colour: p.amber, values: shocked },
      { name: 'On today’s curve, held', colour: p.muted, dashed: true, values: base },
    ],
    markers: [],
    digits: DEBT_MEASURES[measure].digits,
  };
}
