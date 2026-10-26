import { Corridor } from '../components/Corridor';
import { bp, pct } from '../lib/format';
import { isCorrPanel } from '../market/types';
import { type Slot, useMarket } from '../store/market';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

/** CORR: the Fed funds market next to India's call money market, each in its own corridor,
 * live from both simulators. */
export function CorrPanel({ slot }: { slot: Slot }) {
  const us = useMarket((s) => s.us);
  const india = useMarket((s) => s.india);
  const data = slot.replies.CORR?.data;
  const reply = isCorrPanel(data) ? data : null;
  const fed = us
    ? {
        lower: us.corridor.lower,
        upper: us.corridor.upper,
        iorb: us.corridor.iorb,
        on_rrp: us.corridor.on_rrp,
        effr: us.effr,
      }
    : (reply?.us ?? null);
  const rbi = india ? { ...india.corridor, wacr: india.wacr } : (reply?.india ?? null);
  if (!fed) return <Waiting what="the US market" />;
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-3">
      <div className="flex flex-col gap-1">
        <span className="text-[10px] tracking-wider text-term-muted">FED FUNDS · TARGET RANGE</span>
        <Corridor
          title="Fed target range"
          floor={{ label: 'LOW', rate: fed.lower }}
          ceiling={{ label: 'HIGH', rate: fed.upper }}
          marks={[
            { label: 'IORB', rate: fed.iorb },
            { label: 'RRP', rate: fed.on_rrp },
          ]}
          value={{ label: 'EFFR', rate: fed.effr }}
        />
        <StatRow>
          <Stat label="EFFR">{pct(fed.effr)}</Stat>
          <Stat label="EFFR − IORB">{bp(fed.effr - fed.iorb, 1)}</Stat>
          <Stat label="RANGE">{bp(fed.upper - fed.lower)} wide</Stat>
          <Stat label="FLOOR">ON RRP {pct(fed.on_rrp)}</Stat>
        </StatRow>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-[10px] tracking-wider text-term-muted">INDIA CALL MONEY · RBI&apos;S LAF CORRIDOR</span>
        {rbi ? (
          <>
            <Corridor
              title="RBI LAF corridor"
              floor={{ label: 'SDF', rate: rbi.sdf }}
              ceiling={{ label: 'MSF', rate: rbi.msf }}
              marks={[{ label: 'REPO', rate: rbi.repo }]}
              value={{ label: 'WACR', rate: rbi.wacr }}
            />
            <StatRow>
              <Stat label="WACR">{pct(rbi.wacr)}</Stat>
              <Stat label="WACR − REPO">{bp(rbi.wacr - rbi.repo, 1)}</Stat>
              <Stat label="CORRIDOR">{bp(rbi.msf - rbi.sdf)} wide</Stat>
              <Stat label="POLICY GAP, REPO − IORB">{bp(rbi.repo - fed.iorb)}</Stat>
            </StatRow>
          </>
        ) : (
          <Waiting what="the India market" />
        )}
      </div>
      <TeachNote code="CORR" />
    </div>
  );
}
