import { describe, expect, it } from 'vitest';

import type { ChartOption } from '../components/Chart';
import { nssQuoteYield } from '../lib/nss';
import { palette } from '../lib/palette';
import { GSEC_YEARS } from '../market/types';
import { GSEC_DATA, GSEC_TICK, SPRD_DATA } from '../test/marketData';
import { gsecCurveOption, passThroughOption, spreadOption } from './gsecOptions';

interface Series {
  name: string;
  data: [number | string, number | null][];
  yAxisIndex?: number;
  markLine?: { data: unknown[] };
}

const named = (option: ChartOption, name: string) =>
  (option.series as Series[]).find((s) => s.name === name);

describe('G-sec chart options', () => {
  it('plots the market points at their maturities and the live NSS fit through them', () => {
    const option = gsecCurveOption(GSEC_YEARS, GSEC_TICK.points, GSEC_TICK.nss, GSEC_DATA.close, palette());
    const market = named(option, 'Market');
    expect(market?.data).toContainEqual([10, 7.41]);
    expect(market?.data).toHaveLength(11);
    const fit = named(option, 'NSS fit');
    const ten = fit?.data.find(([t]) => t === 10);
    expect(ten?.[1]).toBeCloseTo(nssQuoteYield(GSEC_TICK.nss, 10) * 100, 10);
    expect(named(option, 'FBIL close')?.data).toHaveLength(11);
    expect(named(option, 'Zero')).toBeDefined();
  });

  it('draws the event study with its bands, the fitted β and its two parts', () => {
    const option = passThroughOption(GSEC_DATA.passthrough, palette());
    const study = named(option, 'Event study');
    expect(study?.data).toContainEqual([2, 0.732]);
    // The 2Y band's top (1.94) is clipped to the axis.
    expect(study?.markLine?.data).toContainEqual([{ coord: [2, 0.24] }, { coord: [2, 1.75] }]);
    expect(named(option, 'β fit')?.data).toContainEqual([10, 0.54]);
    expect(named(option, 'Expectations')?.data).toContainEqual([10, 0.171]);
    expect(named(option, 'Term premium')?.data).toContainEqual([10, 0.37]);
    expect(named(option, 'On the day')?.data).toContainEqual([10, 0.129]);
  });

  it('puts the 10-year yields on the left axis and the spread in bp on the right', () => {
    const simulated = [{ date: '2026-10-20', india: 0.0745, us: 0.041 }];
    const option = spreadOption({ ...SPRD_DATA, simulated }, palette());
    const india = named(option, 'India 10Y')?.data ?? [];
    expect(india.map(([d]) => d)).toEqual(['2026-10-09', '2026-10-12', '2026-10-20']);
    expect(india[2]?.[1]).toBeCloseTo(7.45, 10);
    const real = named(option, 'Spread');
    expect(real?.yAxisIndex).toBe(1);
    expect(real?.data[1]?.[1]).toBeCloseTo(232, 9);
    expect(named(option, 'Spread (sim)')?.data[0]?.[1]).toBeCloseTo(335, 9);
  });
});
