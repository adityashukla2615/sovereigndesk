import { Corridor } from '../components/Corridor';
import { croreCount, inrCr, pct } from '../lib/format';
import { isLafPanel } from '../market/types';
import { type Slot, useMarket } from '../store/market';
import { send } from '../ws/session';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

function istTime(iso: string): string {
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)} ${iso.slice(11, 16)}`;
}

/** LAF: RBI's liquidity adjustment facility. Last night's standing facilities, the VRR and VRRR
 * outstanding, the net position as a share of NDTL, the auctions run, and how likely RBI's fitted
 * reaction makes the next one. */
export function LafPanel({ slot }: { slot: Slot }) {
  const india = useMarket((s) => s.india);
  const data = slot.replies.LAF?.data;
  const panel = isLafPanel(data) ? data : null;
  if (!india) return <Waiting what="the India market" />;
  const c = india.corridor;
  const surplus = india.surplus;
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      <Corridor
        title="RBI LAF corridor"
        floor={{ label: 'SDF', rate: c.sdf }}
        ceiling={{ label: 'MSF', rate: c.msf }}
        marks={[{ label: 'REPO', rate: c.repo }]}
        value={{ label: 'WACR', rate: india.wacr }}
        target={{ label: 'map', rate: india.map_rate }}
      />
      <StatRow>
        <Stat label="NET LAF" tone={surplus >= 0 ? 'text-term-up' : 'text-term-down'}>
          {surplus >= 0 ? 'absorbing ' : 'injecting '}
          {inrCr(Math.abs(surplus))} · {india.surplus_pct.toFixed(2)}% NDTL
        </Stat>
        <Stat label="SDF / MSF LAST NIGHT">
          {inrCr(india.laf.sdf)} / {inrCr(india.laf.msf)}
        </Stat>
        <Stat label="VRRR / VRR OUT">
          {inrCr(india.laf.vrrr)} / {inrCr(india.laf.vrr)}
        </Stat>
        {panel && (
          <Stat label={`DURABLE (${panel.durable_as_of})`}>{inrCr(panel.durable_liquidity)}</Stat>
        )}
        {panel && (
          <Stat label="RBI'S NEXT MOVE">
            {panel.reaction.enabled
              ? `VRR ${(panel.reaction.vrr_probability * 100).toFixed(0)}% · VRRR ${(panel.reaction.vrrr_probability * 100).toFixed(0)}%`
              : 'reaction off'}
          </Stat>
        )}
      </StatRow>
      {!panel ? (
        <Waiting what="RBI's operations (type LAF)" />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto">
          <table className="text-[10px]" aria-label="operations outstanding">
            <thead>
              <tr className="text-term-muted">
                <th className="text-left font-normal">OUTSTANDING</th>
                <th className="px-1 text-right font-normal">₹ CR</th>
                <th className="px-1 text-right font-normal">RATE</th>
                <th className="px-1 text-right font-normal">FROM</th>
                <th className="px-1 text-right font-normal">REVERSES</th>
              </tr>
            </thead>
            <tbody>
              {panel.operations.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-term-muted">
                    none
                  </td>
                </tr>
              )}
              {panel.operations.map((op) => (
                <tr key={`${op.kind}-${op.start}-${op.maturity}-${String(op.amount)}`}>
                  <td className={op.kind === 'VRR' ? 'text-term-up' : 'text-term-accent'}>
                    {op.kind} {op.kind === 'VRR' ? '(injects)' : '(absorbs)'}
                  </td>
                  <td className="px-1 text-right">{croreCount(op.amount)}</td>
                  <td className="px-1 text-right">{pct(op.rate)}</td>
                  <td className="px-1 text-right">{op.start}</td>
                  <td className="px-1 text-right">{op.maturity}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <table className="text-[10px]" aria-label="auctions">
            <thead>
              <tr className="text-term-muted">
                <th className="text-left font-normal">AUCTION (IST)</th>
                <th className="px-1 text-left font-normal">BY</th>
                <th className="px-1 text-right font-normal">NOTIFIED</th>
                <th className="px-1 text-right font-normal">BIDS</th>
                <th className="px-1 text-right font-normal">ALLOTTED</th>
                <th className="px-1 text-right font-normal">CUT-OFF</th>
                <th className="px-1 text-right font-normal">W. AVG</th>
                <th className="px-1 text-right font-normal">DAYS</th>
              </tr>
            </thead>
            <tbody>
              {panel.auctions.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-term-muted">
                    none yet: RBI auctions at 09:30 IST
                  </td>
                </tr>
              )}
              {[...panel.auctions].reverse().map((a) => (
                <tr key={`${a.time}-${a.kind}`} className="whitespace-nowrap">
                  <td className={a.kind === 'VRR' ? 'text-term-up' : 'text-term-accent'}>
                    {istTime(a.time)} {a.kind}
                  </td>
                  <td className="px-1 text-term-muted">{a.manual ? 'you' : 'RBI'}</td>
                  <td className="px-1 text-right">{croreCount(a.notified)}</td>
                  <td className="px-1 text-right">{croreCount(a.received)}</td>
                  <td className="px-1 text-right">{croreCount(a.allotted)}</td>
                  <td className="px-1 text-right">{pct(a.cut_off)}</td>
                  <td className="px-1 text-right">{pct(a.weighted_average)}</td>
                  <td className="px-1 text-right">{String(a.tenor_days)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[10px] text-term-muted">
            Order one: <span className="text-term-amber">VRR 50000CR 7D</span> injects,{' '}
            <span className="text-term-amber">VRRR 50000CR 7D</span> absorbs; it runs at the next 09:30 IST.{' '}
            <button
              type="button"
              onClick={() => {
                send({ op: 'command', text: 'LAF' });
              }}
              className="rounded-sm border border-term-line px-1 text-term-amber hover:border-term-amber"
              aria-label="refresh RBI's operations"
            >
              ↻
            </button>
          </p>
        </div>
      )}
      <TeachNote code="LAF" />
    </div>
  );
}
