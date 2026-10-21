import { Suspense, lazy } from 'react';

import type { TimeChartData } from './TimeChart';

// Lightweight Charts loads on first use, like ECharts, so the shell paints first.
const TimeChart = lazy(() => import('./TimeChart').then((m) => ({ default: m.TimeChart })));

/** A time chart that loads its library on first use; the box keeps its place meanwhile. */
export function LazyTimeChart({ data, label }: { data: TimeChartData; label: string }) {
  return (
    <Suspense fallback={<div role="img" aria-label={label} className="h-full min-h-0 w-full min-w-0" />}>
      <TimeChart data={data} label={label} />
    </Suspense>
  );
}
