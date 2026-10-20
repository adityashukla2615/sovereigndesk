import { useMemo } from 'react';

import { LazyChart as Chart } from '../components/LazyChart';
import { bp, pct } from '../lib/format';
import { palette } from '../lib/palette';
import { isPriceYield } from '../market/types';
import { type Slot, useMarket } from '../store/market';
import { priceYieldOption } from './options';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

/** PY: a par bond at the current yield, its risk measures, and how good the approximations are. */
export function PyPanel({ slot }: { slot: Slot }) {
  const data = slot.replies.PY?.data;
  const py = isPriceYield(data) ? data : null;
  const live = useMarket((s) => (py ? s.us?.curve[py.tenor] : undefined));
  const shiftBp = py && live !== undefined ? Math.round((live - py.ytm) * 1e4) : null;
  const option = useMemo(() => (py ? priceYieldOption(py, palette(), shiftBp) : null), [py, shiftBp]);
  if (!py || !option) return <Waiting what="the price–yield panel (type PY 10Y)" />;
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <StatRow>
        <Stat label={`${py.tenor} PAR YIELD`}>{pct(py.ytm, 3)}</Stat>
        {live !== undefined && (
          <Stat label="NOW" tone="text-term-amber">
            {pct(live, 3)} ({bp(live - py.ytm, 1)})
          </Stat>
        )}
        <Stat label="PRICE">{py.price.toFixed(3)}</Stat>
        <Stat label="MOD DURATION">{py.modified.toFixed(2)}</Stat>
        <Stat label="MACAULAY">{py.macaulay.toFixed(2)}</Stat>
        <Stat label="CONVEXITY">{py.convexity.toFixed(1)}</Stat>
        <Stat label="DV01 /100">{py.dv01.toFixed(4)}</Stat>
      </StatRow>
      <div className="min-h-40 flex-1">
        <Chart option={option} label={`${py.tenor} price against yield change`} />
      </div>
      <TeachNote code="PY" />
    </div>
  );
}
