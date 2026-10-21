import {
  ColorType,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type Time,
  type WhitespaceData,
} from 'lightweight-charts';
import { useEffect, useRef } from 'react';

import { palette } from '../lib/palette';

export interface TimeLine {
  name: string;
  colour: string;
  dashed?: boolean;
  /** One value per date of the chart; null where it is unknown (or not revealed yet). */
  values: (number | null)[];
}

export interface TimeMarker {
  date: string;
  text: string;
}

/** What a time chart draws: lines over shared business days, with markers on the first. */
export interface TimeChartData {
  dates: string[];
  lines: TimeLine[];
  markers: TimeMarker[];
  digits: number;
}

function points(dates: string[], values: (number | null)[]): (LineData | WhitespaceData)[] {
  return dates.map((time, i) => {
    const value = values[i];
    return value === null || value === undefined || !Number.isFinite(value) ? { time } : { time, value };
  });
}

function monoFont(): string {
  const style = typeof document === 'undefined' ? null : getComputedStyle(document.documentElement);
  const font = style?.getPropertyValue('--font-mono').trim() ?? '';
  return font || 'monospace';
}

/** A TradingView Lightweight Charts™ time series that fills its box and follows its size. The
 * axis stays fixed to every date, so lines revealed day by day grow across it. */
export function TimeChart({ data, label }: { data: TimeChartData; label: string }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const linesRef = useRef<ISeriesApi<'Line'>[]>([]);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const p = palette();
    const chart = createChart(box, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: p.muted,
        fontSize: 10,
        fontFamily: monoFont(),
      },
      grid: { vertLines: { color: p.line }, horzLines: { color: p.line } },
      rightPriceScale: { borderColor: p.line },
      timeScale: { borderColor: p.line, fixLeftEdge: true, fixRightEdge: true },
      handleScroll: false,
      handleScale: false,
    });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
      linesRef.current = [];
      markersRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.applyOptions({ localization: { priceFormatter: (v: number) => v.toFixed(data.digits) } });
    const lines = linesRef.current;
    while (lines.length > data.lines.length) {
      const extra = lines.pop();
      if (extra) chart.removeSeries(extra);
    }
    data.lines.forEach((line, k) => {
      const options = {
        color: line.colour,
        lineWidth: 2 as const,
        lineStyle: line.dashed ? LineStyle.Dashed : LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: false,
      };
      let series = lines[k];
      if (series) {
        series.applyOptions(options);
      } else {
        series = chart.addSeries(LineSeries, options);
        lines[k] = series;
      }
      series.setData(points(data.dates, line.values));
    });
    const first = lines[0];
    if (first) {
      const p = palette();
      markersRef.current ??= createSeriesMarkers(first, []);
      markersRef.current.setMarkers(
        data.markers.map((m) => ({
          time: m.date,
          position: 'aboveBar' as const,
          shape: 'arrowDown' as const,
          color: p.amber,
          text: m.text,
        })),
      );
    }
    chart.timeScale().fitContent();
  }, [data]);

  return <div ref={boxRef} role="img" aria-label={label} className="h-full min-h-0 w-full min-w-0" />;
}
