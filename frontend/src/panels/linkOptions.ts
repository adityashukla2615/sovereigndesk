/** ECharts option for the LINK panel: a pure function of its data, so it is testable. */

import type { ChartOption } from '../components/Chart';
import type { Palette } from '../lib/palette';
import type { LinkPanelData } from '../market/types';
import { axis, base } from './options';

/** The chain day by day: FPI flows and RBI's dollar trades (cumulative, US$ bn) and the
 * liquidity surplus (% of NDTL) they leave, with the simulation's progress marked. */
export function linkOption(panel: LinkPanelData, p: Palette, day = panel.progress.day): ChartOption {
  const days = panel.path.fpi_bn.map((_, i) => i + 1);
  const line = (name: string, values: number[], color: string, yAxisIndex = 0) => ({
    name,
    type: 'line' as const,
    showSymbol: false,
    yAxisIndex,
    data: values.map((v, i) => [days[i] ?? i + 1, v]),
    lineStyle: { color, width: 2 },
    itemStyle: { color },
  });
  const fpi = line('FPI flows (US$ bn)', panel.path.fpi_bn, p.down);
  return {
    ...base(p),
    grid: { left: 46, right: 46, top: 26, bottom: 28 },
    xAxis: {
      type: 'value',
      name: 'business day',
      nameLocation: 'middle',
      nameGap: 18,
      min: 1,
      max: days.length,
      ...axis(p),
    },
    yAxis: [
      { type: 'value', name: 'US$ bn', nameLocation: 'middle', nameGap: 32, scale: true, ...axis(p) },
      {
        type: 'value',
        name: '% of NDTL',
        nameLocation: 'middle',
        nameGap: 34,
        scale: true,
        ...axis(p),
        splitLine: { show: false },
      },
    ],
    series: [
      {
        ...fpi,
        markLine:
          panel.mode === 'run' && day > 0
            ? {
                symbol: 'none',
                silent: true,
                lineStyle: { color: p.text, type: 'dashed' },
                label: { color: p.text, fontSize: 10, formatter: 'now', position: 'end' },
                data: [{ xAxis: day }],
              }
            : undefined,
      },
      line("RBI's dollar trades (US$ bn)", panel.path.rbi_bn, p.amber),
      line('Surplus (% of NDTL)', panel.path.surplus_pct, p.accent, 1),
    ],
  };
}
