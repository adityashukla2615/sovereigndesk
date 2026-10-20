import { LineChart, ScatterChart } from 'echarts/charts';
import {
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components';
import { type ECharts, type EChartsCoreOption, init, use as registerModules } from 'echarts/core';
import { SVGRenderer } from 'echarts/renderers';
import { useEffect, useRef } from 'react';

// Tree-shaken ECharts: only the chart types and components the panels use.
registerModules([
  LineChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  SVGRenderer,
]);

export type ChartOption = EChartsCoreOption;

/** An ECharts chart that fills its box and follows it when the panel is resized. */
export function Chart({ option, label }: { option: ChartOption; label: string }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ECharts | null>(null);

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const chart = init(box, undefined, { renderer: 'svg' });
    chartRef.current = chart;
    const observer =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() => {
            chart.resize();
          });
    observer?.observe(box);
    return () => {
      observer?.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true, lazyUpdate: true });
  }, [option]);

  return <div ref={boxRef} role="img" aria-label={label} className="h-full min-h-0 w-full min-w-0" />;
}
