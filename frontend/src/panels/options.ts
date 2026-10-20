/** ECharts options for the market panels: pure functions of panel data, so they are testable. */

import type { ChartOption } from '../components/Chart';
import type { Palette } from '../lib/palette';
import type {
  CorridorPanelData,
  Curve,
  PriceYieldData,
  QtProjection,
  ReserveCurve,
} from '../market/types';

type Point = [number, number];

function axis(p: Palette) {
  return {
    axisLine: { lineStyle: { color: p.line } },
    axisLabel: { color: p.muted, fontSize: 10, fontFamily: 'IBM Plex Mono, monospace' },
    nameTextStyle: { color: p.muted, fontSize: 10 },
    splitLine: { lineStyle: { color: p.line, opacity: 0.5 } },
  };
}

function base(p: Palette): ChartOption {
  return {
    animation: false,
    textStyle: { fontFamily: 'IBM Plex Mono, monospace', color: p.text },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.panel,
      borderColor: p.line,
      textStyle: { color: p.text, fontSize: 11 },
    },
    legend: { top: 0, right: 0, textStyle: { color: p.muted, fontSize: 10 }, itemHeight: 8 },
  };
}

function zip(xs: readonly number[], ys: readonly number[]): Point[] {
  return xs.map((x, i) => [x, ys[i] ?? Number.NaN]);
}

/** Price change (%) against a parallel yield shift: exact, duration and duration + convexity. */
export function priceYieldOption(py: PriceYieldData, p: Palette, liveShiftBp: number | null): ChartOption {
  const first = py.shifts_bp[0] ?? -300;
  const last = py.shifts_bp[py.shifts_bp.length - 1] ?? 300;
  return {
    ...base(p),
    grid: { left: 44, right: 10, top: 24, bottom: 30 },
    xAxis: {
      type: 'value',
      name: 'yield change (bp)',
      nameLocation: 'middle',
      nameGap: 20,
      min: first,
      max: last,
      ...axis(p),
    },
    yAxis: { type: 'value', name: 'price change (%)', scale: true, ...axis(p) },
    series: [
      {
        name: 'Exact',
        type: 'line',
        showSymbol: false,
        data: zip(py.shifts_bp, py.exact.map((v) => v * 100)),
        lineStyle: { color: p.amber, width: 2 },
        itemStyle: { color: p.amber },
        markLine:
          liveShiftBp === null
            ? undefined
            : {
                symbol: 'none',
                silent: true,
                lineStyle: { color: p.text, type: 'dashed' },
                label: { color: p.text, fontSize: 10, formatter: 'now', position: 'start' },
                data: [{ xAxis: liveShiftBp }],
              },
      },
      {
        name: 'Duration',
        type: 'line',
        showSymbol: false,
        data: zip(py.shifts_bp, py.duration_only.map((v) => v * 100)),
        lineStyle: { color: p.accent, type: 'dashed' },
        itemStyle: { color: p.accent },
      },
      {
        name: 'Duration + convexity',
        type: 'line',
        showSymbol: false,
        data: zip(py.shifts_bp, py.duration_convexity.map((v) => v * 100)),
        lineStyle: { color: p.up, type: 'dotted', width: 2 },
        itemStyle: { color: p.up },
      },
    ],
  };
}

/** EFFR − IORB (decimal) at a reserves / bank-assets ratio: the fitted logistic. */
export function reserveSpread(curve: ReserveCurve, ratio: number): number {
  const z = Math.max(-60, Math.min(60, (ratio - curve.midpoint) / curve.width));
  return curve.abundant + (curve.scarce - curve.abundant) / (1 + Math.exp(z));
}

/** The reserve-demand curve with where the system is now. */
export function reserveCurveOption(
  curve: ReserveCurve,
  p: Palette,
  now: { ratio: number; spread: number } | null,
): ChartOption {
  const xs = Array.from({ length: 81 }, (_, i) => 0.04 + (i * 0.16) / 80);
  return {
    ...base(p),
    grid: { left: 44, right: 10, top: 24, bottom: 30 },
    xAxis: {
      type: 'value',
      name: 'reserves / bank assets (%)',
      nameLocation: 'middle',
      nameGap: 20,
      min: 4,
      max: 20,
      ...axis(p),
    },
    yAxis: { type: 'value', name: 'EFFR − IORB (bp)', ...axis(p) },
    series: [
      {
        name: 'Fitted demand',
        type: 'line',
        showSymbol: false,
        data: xs.map((x): Point => [x * 100, reserveSpread(curve, x) * 1e4]),
        lineStyle: { color: p.accent, width: 2 },
        itemStyle: { color: p.accent },
      },
      ...(now
        ? [
            {
              name: 'Now',
              type: 'scatter',
              symbolSize: 9,
              data: [[now.ratio * 100, now.spread * 1e4]],
              itemStyle: { color: p.amber },
            },
          ]
        : []),
    ],
  };
}

/** A QT plan's path: reserves ($tn) and the EFFR − IORB spread (bp), month by month. */
export function qtOption(qt: QtProjection, p: Palette): ChartOption {
  const months = qt.reserves.map((_, i) => i + 1);
  const chart = base(p);
  return {
    ...chart,
    legend: { ...(chart.legend as object), top: 0, right: 'center' },
    grid: { left: 44, right: 44, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: months, name: 'months ahead', nameLocation: 'middle', nameGap: 18, ...axis(p) },
    yAxis: [
      { type: 'value', name: 'reserves ($tn)', scale: true, ...axis(p) },
      { type: 'value', name: 'spread (bp)', scale: true, ...axis(p), splitLine: { show: false } },
    ],
    series: [
      {
        name: 'Reserves',
        type: 'line',
        showSymbol: false,
        data: qt.reserves.map((r) => r / 1000),
        lineStyle: { color: p.amber },
        itemStyle: { color: p.amber },
      },
      {
        name: 'EFFR − IORB',
        type: 'line',
        yAxisIndex: 1,
        showSymbol: false,
        data: qt.effr_iorb_spread.map((s) => s * 1e4),
        lineStyle: { color: p.down, type: 'dashed' },
        itemStyle: { color: p.down },
      },
    ],
  };
}

/** WACR − repo (decimal) at a surplus of `surplusPct` % of NDTL: the fitted macro map. */
export function mapSpread(map: CorridorPanelData['map'], surplusPct: number): number {
  const z = Math.max(-60, Math.min(60, (surplusPct - map.midpoint) / map.width));
  return map.deficit + (map.surplus - map.deficit) / (1 + Math.exp(-z));
}

/** The macro map drawn against today's corridor, with where WACR and the system are now. */
export function macroMapOption(
  map: CorridorPanelData['map'],
  corridor: { sdf: number; repo: number; msf: number },
  now: { surplus_pct: number; wacr: number } | null,
  p: Palette,
): ChartOption {
  const xs = Array.from({ length: 61 }, (_, i) => -2 + i * 0.1);
  const rate = (x: number) =>
    Math.min(corridor.msf, Math.max(corridor.sdf, corridor.repo + mapSpread(map, x)));
  const level = (name: string, value: number, color: string) => ({
    name,
    yAxis: value * 100,
    lineStyle: { color, type: 'dashed' as const },
    label: { color, fontSize: 10, formatter: name, position: 'insideEndTop' as const },
  });
  return {
    ...base(p),
    grid: { left: 44, right: 10, top: 24, bottom: 30 },
    xAxis: {
      type: 'value',
      name: 'surplus (% of NDTL)',
      nameLocation: 'middle',
      nameGap: 20,
      min: -2,
      max: 4,
      ...axis(p),
    },
    yAxis: {
      type: 'value',
      name: 'rate (%)',
      min: (corridor.sdf - 0.001) * 100,
      max: (corridor.msf + 0.001) * 100,
      ...axis(p),
    },
    series: [
      {
        name: 'Macro map',
        type: 'line',
        showSymbol: false,
        data: xs.map((x): Point => [x, rate(x) * 100]),
        lineStyle: { color: p.accent, width: 2 },
        itemStyle: { color: p.accent },
        markLine: {
          symbol: 'none',
          silent: true,
          data: [
            level('MSF', corridor.msf, p.down),
            level('repo', corridor.repo, p.muted),
            level('SDF', corridor.sdf, p.up),
          ],
        },
      },
      ...(now
        ? [
            {
              name: 'WACR now',
              type: 'scatter',
              symbolSize: 9,
              data: [[now.surplus_pct, now.wacr * 100]],
              itemStyle: { color: p.amber },
            },
          ]
        : []),
    ],
  };
}

/** WACR − repo by day: RBI's prints (last 90 days) then the simulated days. */
export function wacrHistoryOption(data: CorridorPanelData, p: Palette): ChartOption {
  const real = data.real.map((d) => [d.date, d.spread * 1e4]);
  const simulated = data.simulated.map((d) => [d.date, d.spread * 1e4]);
  return {
    ...base(p),
    grid: { left: 44, right: 10, top: 24, bottom: 24 },
    xAxis: { type: 'time', ...axis(p) },
    yAxis: { type: 'value', name: 'WACR − repo (bp)', ...axis(p) },
    series: [
      {
        name: 'RBI (real)',
        type: 'line',
        showSymbol: false,
        data: real,
        lineStyle: { color: p.muted },
        itemStyle: { color: p.muted },
      },
      {
        name: 'Simulated',
        type: 'line',
        showSymbol: simulated.length < 3,
        data: simulated,
        lineStyle: { color: p.amber },
        itemStyle: { color: p.amber },
      },
    ],
  };
}

/** The par curve now against the official close, plus a sale's long-run effect if one is set. */
export function parCurveOption(
  tenors: readonly string[],
  now: Curve,
  close: Curve | null,
  longRun: Curve | null,
  p: Palette,
): ChartOption {
  const line = (name: string, values: (number | null)[], color: string, dashed = false) => ({
    name,
    type: 'line',
    data: values,
    symbolSize: 4,
    lineStyle: { color, type: dashed ? ('dashed' as const) : ('solid' as const) },
    itemStyle: { color },
  });
  const pctOf = (curve: Curve) => tenors.map((t) => (curve[t] === undefined ? null : (curve[t] ?? 0) * 100));
  return {
    ...base(p),
    grid: { left: 40, right: 10, top: 24, bottom: 24 },
    xAxis: { type: 'category', data: [...tenors], ...axis(p) },
    yAxis: { type: 'value', name: 'yield (%)', scale: true, ...axis(p) },
    series: [
      line('Now', pctOf(now), p.amber),
      ...(close ? [line('Official close', pctOf(close), p.muted, true)] : []),
      ...(longRun
        ? [
            line(
              'After the sale (long run)',
              tenors.map((t) => {
                const base = now[t];
                const move = longRun[t];
                return base === undefined || move === undefined ? null : (base + move) * 100;
              }),
              p.down,
              true,
            ),
          ]
        : []),
    ],
  };
}
