import { useMemo } from 'react';

import { LazyChart as Chart } from '../components/LazyChart';
import { bp, pct } from '../lib/format';
import { palette } from '../lib/palette';
import { DISPLAY_TENORS, curveOf } from '../market/types';
import { type Slot, useMarket } from '../store/market';
import { parCurveOption } from './options';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

/** UST: the live par curve against the official close, and a foreign sale's long-run effect. */
export function UstPanel({ slot }: { slot: Slot }) {
  const curve = useMarket((s) => s.us?.curve ?? null);
  const close = curveOf(slot.replies.UST?.data, 'official_close');
  const longRun = curveOf(slot.replies.SHOCK?.data, 'long_run');
  // Redraw when a yield moves by a tenth of a basis point, not on every tick.
  const key = curve ? DISPLAY_TENORS.map((t) => (curve[t] ?? 0).toFixed(5)).join(',') : '';
  const option = useMemo(() => {
    if (!key) return null;
    const values = key.split(',').map(Number);
    const rounded = Object.fromEntries(DISPLAY_TENORS.map((t, i) => [t, values[i] ?? 0]));
    return parCurveOption(DISPLAY_TENORS, rounded, close, longRun, palette());
  }, [key, close, longRun]);
  if (!curve || !option) return <Waiting what="the US market" />;
  const two = curve['2Y'];
  const ten = curve['10Y'];
  const thirty = curve['30Y'];
  const change = (tenor: string) => {
    const now = curve[tenor];
    const then = close?.[tenor];
    return now !== undefined && then !== undefined ? ` (${bp(now - then, 1)})` : '';
  };
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <StatRow>
        <Stat label="2Y">
          {pct(two, 3)}
          {change('2Y')}
        </Stat>
        <Stat label="10Y">
          {pct(ten, 3)}
          {change('10Y')}
        </Stat>
        <Stat label="30Y">
          {pct(thirty, 3)}
          {change('30Y')}
        </Stat>
        {two !== undefined && ten !== undefined && <Stat label="2s10s">{bp(ten - two)}</Stat>}
      </StatRow>
      <div className="min-h-40 flex-1">
        <Chart option={option} label="Treasury par curve, live against the official close" />
      </div>
      <TeachNote code="UST" />
    </div>
  );
}
