/** ECharts options for the G-sec panels (GSEC, SPRD): pure functions of panel data. */

import type { ChartOption } from '../components/Chart';
import { type Nss, nssQuoteYield, nssZero } from '../lib/nss';
import type { Palette } from '../lib/palette';
import type { Curve, GsecPanelData, SpreadPanelData } from '../market/types';
import { axis, base } from './options';

type Point = [number, number];

/** Maturities the fitted curves are drawn on: bills, then the semi-annual coupon grid. */
const GRID = [0.25, 0.5, 0.75, ...Array.from({ length: 59 }, (_, i) => 1 + i * 0.5)];

/** A y-axis whose name runs along it, leaving the top of the chart to the legend. */
function sideAxis(name: string, p: Palette, gap = 30) {
  return {
    type: 'value' as const,
    name,
    nameLocation: 'middle' as const,
    nameGap: gap,
    scale: true,
    ...axis(p),
  };
}

function maturityAxis(p: Palette) {
  return {
    type: 'value' as const,
    name: 'maturity (years)',
    nameLocation: 'middle' as const,
    nameGap: 20,
    min: 0,
    max: 30,
    ...axis(p),
  };
}

/**
 * The G-sec curve by maturity: the market points now, the live NSS fit through them (bills at
 * their simple yield, bonds at par), its zero curve (semi-annual), and the curve on FBIL's day.
 */
export function gsecCurveOption(
  tenors: Record<string, number>,
  points: Curve,
  nss: Nss,
  close: Curve | null,
  p: Palette,
): ChartOption {
  const at = (curve: Curve): Point[] =>
    Object.entries(tenors)
      .filter(([t]) => curve[t] !== undefined)
      .map(([t, years]) => [years, (curve[t] ?? 0) * 100]);
  return {
    ...base(p),
    grid: { left: 44, right: 10, top: 24, bottom: 30 },
    xAxis: maturityAxis(p),
    yAxis: sideAxis('yield (%)', p),
    series: [
      {
        name: 'NSS fit',
        type: 'line',
        showSymbol: false,
        data: GRID.map((t): Point => [t, nssQuoteYield(nss, t) * 100]),
        lineStyle: { color: p.amber, width: 2 },
        itemStyle: { color: p.amber },
      },
      {
        name: 'Market',
        type: 'scatter',
        symbolSize: 7,
        data: at(points),
        itemStyle: { color: p.text },
      },
      {
        name: 'Zero',
        type: 'line',
        showSymbol: false,
        data: GRID.map((t): Point => [t, 2 * Math.expm1(nssZero(nss, t) / 2) * 100]),
        lineStyle: { color: p.accent, type: 'dotted' },
        itemStyle: { color: p.accent },
      },
      ...(close
        ? [
            {
              name: 'FBIL close',
              type: 'line',
              data: at(close),
              symbolSize: 4,
              lineStyle: { color: p.muted, type: 'dashed' },
              itemStyle: { color: p.muted },
            },
          ]
        : []),
    ],
  };
}

const FLOOR = -0.25;
const CEILING = 1.75;

/**
 * Repo pass-through by maturity: the event study's ratios with their bootstrap bands, the
 * fitted β split into expectations and term premium, and the same-day slopes on the actual
 * change (small, because most changes were expected).
 */
export function passThroughOption(data: GsecPanelData['passthrough'], p: Palette): ChartOption {
  const clip = (v: number) => Math.min(CEILING, Math.max(FLOOR, v));
  const line = (name: string, key: 'beta' | 'expectations' | 'tp', color: string, type: string) => ({
    name,
    type: 'line',
    showSymbol: false,
    data: data.curve.map((r): Point => [r.years, r[key]]),
    lineStyle: { color, type, width: key === 'beta' ? 2 : 1 },
    itemStyle: { color },
  });
  return {
    ...base(p),
    grid: { left: 44, right: 10, top: 40, bottom: 30 },
    xAxis: maturityAxis(p),
    yAxis: { ...sideAxis('per unit of surprise', p), scale: false, min: FLOOR, max: CEILING },
    series: [
      line('β fit', 'beta', p.amber, 'solid'),
      line('Expectations', 'expectations', p.accent, 'dashed'),
      line('Term premium', 'tp', p.up, 'dotted'),
      {
        name: 'Event study',
        type: 'scatter',
        symbolSize: 7,
        data: data.estimates.map((e): Point => [e.years, clip(e.relative)]),
        itemStyle: { color: p.text },
        markLine: {
          symbol: ['none', 'none'],
          silent: true,
          lineStyle: { color: p.muted, type: 'solid', width: 1 },
          label: { show: false },
          data: data.estimates.map((e) => [
            { coord: [e.years, clip(e.low)] },
            { coord: [e.years, clip(e.high)] },
          ]),
        },
      },
      {
        name: 'On the day',
        type: 'scatter',
        symbol: 'emptyCircle',
        symbolSize: 6,
        data: data.estimates.map((e): Point => [e.years, e.day_beta]),
        itemStyle: { color: p.muted },
      },
    ],
  };
}

/** India 10Y against US 10Y (left axis, %) and the spread between them (right axis, bp). */
export function spreadOption(data: SpreadPanelData, p: Palette): ChartOption {
  const rows = [...data.real, ...data.simulated];
  const firstSimulated = data.simulated[0]?.date ?? null;
  const yields = (key: 'india' | 'us') =>
    rows.map((r) => {
      const value = r[key];
      return [r.date, value === null ? null : value * 100];
    });
  const spread = (list: SpreadPanelData['real']) =>
    list.flatMap((r) => (r.us === null ? [] : [[r.date, (r.india - r.us) * 1e4]]));
  return {
    ...base(p),
    grid: { left: 44, right: 50, top: 24, bottom: 24 },
    xAxis: { type: 'time', ...axis(p) },
    yAxis: [
      sideAxis('10Y yield (%)', p),
      { ...sideAxis('India − US (bp)', p, 36), splitLine: { show: false } },
    ],
    series: [
      {
        name: 'India 10Y',
        type: 'line',
        showSymbol: false,
        data: yields('india'),
        lineStyle: { color: p.amber },
        itemStyle: { color: p.amber },
        markLine: firstSimulated
          ? {
              symbol: 'none',
              silent: true,
              lineStyle: { color: p.muted, type: 'dashed' },
              label: { color: p.muted, fontSize: 10, formatter: 'simulated', position: 'insideStartTop' },
              data: [{ xAxis: firstSimulated }],
            }
          : undefined,
      },
      {
        name: 'US 10Y',
        type: 'line',
        showSymbol: false,
        data: yields('us'),
        lineStyle: { color: p.accent },
        itemStyle: { color: p.accent },
      },
      {
        name: 'Spread',
        type: 'line',
        yAxisIndex: 1,
        showSymbol: false,
        data: spread(data.real),
        lineStyle: { color: p.muted },
        itemStyle: { color: p.muted },
      },
      {
        name: 'Spread (sim)',
        type: 'line',
        yAxisIndex: 1,
        showSymbol: data.simulated.length < 3,
        data: spread(data.simulated),
        lineStyle: { color: p.text },
        itemStyle: { color: p.text },
      },
    ],
  };
}
