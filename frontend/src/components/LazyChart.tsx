import { Suspense, lazy } from 'react';

import type { ChartOption } from './Chart';

// ECharts is the heaviest dependency: load it after the shell has painted.
const Chart = lazy(() => import('./Chart').then((m) => ({ default: m.Chart })));

/** A chart that loads ECharts on first use; the box keeps its place meanwhile. */
export function LazyChart({ option, label }: { option: ChartOption; label: string }) {
  return (
    <Suspense fallback={<div role="img" aria-label={label} className="h-full min-h-0 w-full min-w-0" />}>
      <Chart option={option} label={label} />
    </Suspense>
  );
}
