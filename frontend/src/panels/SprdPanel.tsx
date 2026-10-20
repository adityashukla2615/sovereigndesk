import { useMemo } from 'react';

import { LazyChart as Chart } from '../components/LazyChart';
import { bp, pct } from '../lib/format';
import { palette } from '../lib/palette';
import { isSpreadPanel } from '../market/types';
import { type Slot, useMarket } from '../store/market';
import { spreadOption } from './gsecOptions';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

/** SPRD: India's 10-year against the US 10-year, real history, simulated closes and now. */
export function SprdPanel({ slot }: { slot: Slot }) {
  const india = useMarket((s) => s.india?.gsec?.points['10Y'] ?? null);
  const us = useMarket((s) => s.us?.curve['10Y'] ?? null);
  const day = useMarket((s) => s.india?.sim_time.slice(0, 10) ?? null);
  const data = slot.replies.SPRD?.data;
  const panel = isSpreadPanel(data) ? data : null;
  // The live point joins the chart when either yield moves by a tenth of a basis point.
  const liveKey =
    india !== null && us !== null && day !== null
      ? `${day},${india.toFixed(5)},${us.toFixed(5)}`
      : '';
  const option = useMemo(() => {
    if (!panel) return null;
    const [date, i, u] = liveKey ? liveKey.split(',') : [];
    const live =
      date && i && u ? [{ date, india: Number(i), us: Number(u) }] : [];
    const simulated = [...panel.simulated.filter((s) => !date || s.date < date), ...live];
    return spreadOption({ ...panel, simulated }, palette());
  }, [panel, liveKey]);
  if (india === null) return <Waiting what="the G-sec curve" />;
  const last = panel?.real.at(-1);
  const lastUs = last?.us ?? null;
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      <StatRow>
        <Stat label="INDIA 10Y">{pct(india, 3)}</Stat>
        <Stat label="US 10Y">{pct(us, 3)}</Stat>
        <Stat label="INDIA − US">{us === null ? '—' : bp(india - us)}</Stat>
        {last && lastUs !== null && (
          <Stat label={`REAL ON ${last.date}`}>{bp(last.india - lastUs)}</Stat>
        )}
      </StatRow>
      <div className="min-h-40 flex-1">
        {option ? (
          <Chart option={option} label="India 10Y against US 10Y and the spread" />
        ) : (
          <Waiting what="the spread history (type SPRD)" />
        )}
      </div>
      <TeachNote code="SPRD" />
    </div>
  );
}
