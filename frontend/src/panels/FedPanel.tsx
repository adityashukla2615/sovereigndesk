import { useMemo } from 'react';

import { LazyChart as Chart } from '../components/LazyChart';
import { Corridor } from '../components/Corridor';
import { bp, pct, usdBn } from '../lib/format';
import { palette } from '../lib/palette';
import { isQtProjection, reserveCurveOf } from '../market/types';
import { type Slot, useMarket } from '../store/market';
import { qtOption, reserveCurveOption } from './options';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

/** FED: the target range with EFFR live, reserves, the fitted demand curve and any QT plan. */
export function FedPanel({ slot }: { slot: Slot }) {
  const us = useMarket((s) => s.us);
  const curve = reserveCurveOf(slot.replies.FED?.data);
  const qtData = slot.replies.QT?.data;
  const qt = isQtProjection(qtData) ? qtData : null;
  // Re-plot only when the point moves visibly (0.01% of assets, 0.1 bp), not on every tick.
  const ratio = us ? Math.round(us.reserves_ratio * 1e4) / 1e4 : null;
  const spread = us ? Math.round((us.effr - us.corridor.iorb) * 1e5) / 1e5 : null;
  const curveOption = useMemo(() => {
    if (!curve) return null;
    const now = ratio !== null && spread !== null ? { ratio, spread } : null;
    return reserveCurveOption(curve, palette(), now);
  }, [curve, ratio, spread]);
  const qtChart = useMemo(() => (qt ? qtOption(qt, palette()) : null), [qt]);
  if (!us) return <Waiting what="the US market" />;
  const c = us.corridor;
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <Corridor
        title="Fed target range"
        floor={{ label: 'LOW', rate: c.lower }}
        ceiling={{ label: 'HIGH', rate: c.upper }}
        marks={[
          { label: 'IORB', rate: c.iorb },
          { label: 'RRP', rate: c.on_rrp },
        ]}
        value={{ label: 'EFFR', rate: us.effr }}
        target={{ label: 'target', rate: us.effr_target }}
      />
      <StatRow>
        <Stat label="EFFR − IORB">{bp(us.effr - c.iorb, 1)}</Stat>
        <Stat label="RESERVES">{usdBn(us.reserves)}</Stat>
        <Stat label="OF BANK ASSETS">{(us.reserves_ratio * 100).toFixed(1)}%</Stat>
        <Stat label="ON RRP">{usdBn(us.on_rrp_balance)}</Stat>
        <Stat label="QT / MONTH" tone={us.qt.halted ? 'text-term-down' : undefined}>
          {usdBn(us.qt.treasury_cap)} UST + {usdBn(us.qt.mbs_cap)} MBS
          {us.qt.halted ? ' (halted)' : ''}
        </Stat>
        <Stat label="10Y TERM PREMIUM">{pct(us.term_premium)}</Stat>
      </StatRow>
      <div className={`grid min-h-40 flex-1 gap-2 ${qtChart ? 'grid-cols-2' : 'grid-cols-1'}`}>
        {curveOption ? (
          <Chart option={curveOption} label="Reserve demand: EFFR − IORB against reserves" />
        ) : (
          <Waiting what="the reserve-demand fit (type FED)" />
        )}
        {qtChart && <Chart option={qtChart} label="QT plan: reserves and EFFR − IORB" />}
      </div>
      <TeachNote code="FED" />
    </div>
  );
}
