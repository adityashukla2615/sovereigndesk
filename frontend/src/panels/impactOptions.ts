/** ECharts option for the IMPACT panel's business view: a pure function of its data. */

import type { ChartOption } from '../components/Chart';
import type { Palette } from '../lib/palette';
import type { ImpactBusiness } from '../market/types';
import { axis, base } from './options';

/** A business month by month: the change in interest, imported costs and margin (₹ a month). */
export function businessOption(b: ImpactBusiness, p: Palette): ChartOption {
  // Monthly amounts as steps (the chart bundle registers line and scatter series only).
  const step = (name: string, values: number[], color: string) => ({
    name,
    type: 'line' as const,
    step: 'middle' as const,
    showSymbol: false,
    data: values.map((v, i) => [b.months[i] ?? i + 1, v]),
    lineStyle: { color, width: 2 },
    itemStyle: { color },
  });
  return {
    ...base(p),
    grid: { left: 64, right: 10, top: 26, bottom: 28 },
    xAxis: { type: 'value', name: 'month', nameLocation: 'middle', nameGap: 18, min: 1, max: b.months.length, ...axis(p) },
    yAxis: { type: 'value', name: '₹ a month', nameLocation: 'middle', nameGap: 50, ...axis(p) },
    series: [
      step('Interest', b.interest, p.down),
      step('Imported costs', b.import_cost, p.amber),
      {
        name: 'Margin',
        type: 'line' as const,
        showSymbol: false,
        data: b.margin.map((v, i) => [b.months[i] ?? i + 1, v]),
        lineStyle: { color: p.accent, width: 2 },
        itemStyle: { color: p.accent },
      },
    ],
  };
}
