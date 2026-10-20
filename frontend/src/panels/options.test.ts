import { describe, expect, it } from 'vitest';

import { palette } from '../lib/palette';
import { CORRIDOR_DATA, PY_DATA } from '../test/marketData';
import {
  macroMapOption,
  mapSpread,
  priceYieldOption,
  reserveCurveOption,
  reserveSpread,
} from './options';

type Series = { name: string; data: [number, number][] }[];

describe('chart options', () => {
  it('evaluates the fitted curves exactly as the engine does', () => {
    const curve = { abundant: -0.00065, scarce: 0.00019, midpoint: 0.115, width: 0.01, fit_rmse_bp: 2.4 };
    expect(reserveSpread(curve, 0.115)).toBeCloseTo((-0.00065 + 0.00019) / 2, 12);
    expect(reserveSpread(curve, 0.5)).toBeCloseTo(-0.00065, 9);
    expect(mapSpread(CORRIDOR_DATA.map, CORRIDOR_DATA.map.midpoint)).toBeCloseTo((0.00253 - 0.00452) / 2, 12);
    expect(mapSpread(CORRIDOR_DATA.map, 50)).toBeCloseTo(-0.00452, 9);
  });

  it('lets the macro map leave the corridor in realistic mode, within the band', () => {
    const corridor = { sdf: 0.0525, repo: 0.055, msf: 0.0575 };
    const band = { lower: 0.0412, upper: 0.0715 };
    const option = macroMapOption(CORRIDOR_DATA.map, corridor, null, palette(), band);
    const rates = (option.series as Series)[0]?.data.map(([, rate]) => rate) ?? [];
    expect(Math.min(...rates)).toBeLessThan(5.25); // deep surplus: below the SDF
    expect(Math.min(...rates)).toBeGreaterThanOrEqual(4.12);
  });

  it('keeps the macro map inside today’s corridor', () => {
    const corridor = { sdf: 0.0525, repo: 0.055, msf: 0.0575 };
    const option = macroMapOption(CORRIDOR_DATA.map, corridor, { surplus_pct: 0.67, wacr: 0.0528 }, palette());
    const series = option.series as Series;
    const rates = series[0]?.data.map(([, rate]) => rate) ?? [];
    expect(rates.length).toBe(61);
    expect(Math.min(...rates)).toBeGreaterThanOrEqual(5.25);
    expect(Math.max(...rates)).toBeLessThanOrEqual(5.75);
    expect(series[1]?.data).toEqual([[0.67, 5.28]]);
  });

  it('plots exact, duration and duration + convexity prices', () => {
    const option = priceYieldOption(PY_DATA, palette(), 12);
    const series = option.series as Series;
    expect(series.map((s) => s.name)).toEqual(['Exact', 'Duration', 'Duration + convexity']);
    const [shift, change] = series[0]?.data[0] ?? [Number.NaN, Number.NaN];
    expect(shift).toBe(-100);
    expect(change).toBeCloseTo(8.5, 9); // per cent
    const reserve = reserveCurveOption(
      { abundant: -0.00065, scarce: 0.00019, midpoint: 0.115, width: 0.01, fit_rmse_bp: 2.4 },
      palette(),
      { ratio: 0.1265, spread: -0.0007 },
    );
    const points = reserve.series as Series;
    const [x, y] = points[1]?.data[0] ?? [Number.NaN, Number.NaN];
    expect(x).toBeCloseTo(12.65, 9);
    expect(y).toBeCloseTo(-7, 9);
  });
});
