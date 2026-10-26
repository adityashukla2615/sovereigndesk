import { useMemo } from 'react';

import { Corridor } from '../components/Corridor';
import { LazyTimeChart as TimeChart } from '../components/LazyTimeChart';
import { QualityBadge } from '../components/QualityBadge';
import { bp, croreCount, inrCr, pct } from '../lib/format';
import { palette } from '../lib/palette';
import { isCallPanel } from '../market/types';
import { type Slot, useMarket } from '../store/market';
import { send } from '../ws/session';
import { roundsChart } from './timeCharts';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

/** Above repo is tight liquidity, below it surplus (the brief's liquidity signal). */
function spreadTone(spread: number): string {
  if (spread > 0.0005) return 'text-term-down';
  if (spread < -0.0005) return 'text-term-up';
  return 'text-term-text';
}

function Book({ title, rows }: { title: string; rows: { bank: string; amount: number }[] }) {
  return (
    <table className="text-[10px]" aria-label={title}>
      <thead>
        <tr className="text-term-muted">
          <th className="text-left font-normal">{title.toUpperCase()}</th>
          <th className="pl-2 text-right font-normal">₹ CR</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr>
            <td colSpan={2} className="text-term-muted">
              none yet today
            </td>
          </tr>
        )}
        {rows.map((r) => (
          <tr key={r.bank}>
            <td className="text-term-text">{r.bank}</td>
            <td className="pl-2 text-right">{croreCount(r.amount)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** CALL: India's call money market today, the brief's rates panel. Call high and low, WACR,
 * CCIL's segments and the T-bills, each against repo; the clearing rounds; who borrowed and
 * who lent; and the orders that participation limits trimmed. */
export function CallPanel({ slot }: { slot: Slot }) {
  const india = useMarket((s) => s.india);
  const data = slot.replies.CALL?.data;
  const panel = isCallPanel(data) ? data : null;
  const sdf = india?.corridor.sdf ?? null;
  const repo = india?.corridor.repo ?? null;
  const msf = india?.corridor.msf ?? null;
  const chart = useMemo(() => {
    if (!panel || panel.rounds.length === 0 || sdf === null || repo === null || msf === null) return null;
    return roundsChart(panel, { sdf, repo, msf }, palette());
  }, [panel, sdf, repo, msf]);
  if (!india) return <Waiting what="the India market" />;
  const c = india.corridor;
  const rates: [string, number | null, string?][] = [
    ['WACR', india.wacr],
    ['CALL HIGH', india.call.high],
    ['CALL LOW', india.call.low],
    ['LAST PRINT', india.last_print],
    ['TREPS', india.segments.treps, 'CCIL'],
    ['MARKET REPO', india.segments.market_repo, 'CCIL'],
    ['NOTICE', india.segments.notice],
    ['TERM', india.segments.term],
    ['T-BILL 91D', india.tbills['3M'] ?? null, 'FBIL'],
    ['T-BILL 182D', india.tbills['6M'] ?? null, 'FBIL'],
    ['T-BILL 364D', india.tbills['12M'] ?? null, 'FBIL'],
  ];
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      <Corridor
        title="Call money in RBI's corridor"
        floor={{ label: 'SDF', rate: c.sdf }}
        ceiling={{ label: 'MSF', rate: c.msf }}
        marks={[{ label: 'REPO', rate: c.repo }]}
        value={{ label: 'WACR', rate: india.wacr }}
      />
      <StatRow>
        <Stat label={india.session_open ? 'CALL TODAY' : 'CALL (CLOSED)'}>
          {inrCr(india.call.volume)} · {String(india.call.rounds)} rounds
        </Stat>
        <Stat label="RANGE">
          {india.call.low !== null && india.call.high !== null
            ? `${pct(india.call.low)}–${pct(india.call.high)} (${bp(india.call.high - india.call.low)})`
            : '—'}
        </Stat>
        <Stat label="LIMITS TRIMMED" tone={india.rejected_today > 0 ? 'text-term-down' : undefined}>
          {String(india.rejected_today)} orders today
        </Stat>
      </StatRow>
      <div className="grid min-h-48 min-w-0 flex-1 grid-cols-[minmax(0,2fr)_minmax(0,3fr)] grid-rows-[minmax(0,1fr)] gap-2">
        <div className="flex min-h-0 flex-col gap-1.5 overflow-auto">
          <table className="text-[10px]" aria-label="money market rates">
            <thead>
              <tr className="text-term-muted">
                <th className="text-left font-normal">RATE</th>
                <th className="px-1 text-right font-normal">NOW</th>
                <th className="px-1 text-right font-normal">− REPO</th>
              </tr>
            </thead>
            <tbody>
              {rates.map(([label, rate, source]) => (
                <tr key={label} className="whitespace-nowrap">
                  <td className="text-term-text">
                    {label}
                    {source && <span className="text-term-muted"> · {source}</span>}
                  </td>
                  <td className="px-1 text-right">{pct(rate)}</td>
                  <td className={`px-1 text-right ${rate === null ? '' : spreadTone(rate - c.repo)}`}>
                    {rate === null ? '—' : bp(rate - c.repo)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="flex items-center gap-1 text-[10px] text-term-muted">
            T-bills: FBIL benchmarks of {india.tbills_as_of}
            {india.tbills_stale && <QualityBadge labels={[india.tbills_stale]} />}
          </p>
        </div>
        <div className="flex min-h-40 min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2 text-[10px] text-term-muted">
            <span>ROUNDS{panel ? ` AS OF ${panel.time.slice(11, 16)} IST` : ''}</span>
            <button
              type="button"
              aria-label="refresh the call market"
              onClick={() => {
                send({ op: 'command', text: 'CALL' });
              }}
              className="rounded-sm border border-term-line px-1 text-term-amber hover:border-term-amber"
            >
              ↻
            </button>
          </div>
          <div className="min-h-0 flex-1">
            {chart ? (
              <TimeChart data={chart} label="Today's clearing rounds against the corridor" />
            ) : (
              <Waiting what="the first clearing round (09:15 IST)" />
            )}
          </div>
        </div>
      </div>
      {panel && (
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          <Book title="Borrowed" rows={panel.borrowers} />
          <Book title="Lent" rows={panel.lenders} />
          {panel.rejections.length > 0 && (
            <table className="text-[10px]" aria-label="orders trimmed by participation limits">
              <thead>
                <tr className="text-term-muted">
                  <th className="text-left font-normal">TRIMMED</th>
                  <th className="px-1 text-left font-normal">BANK</th>
                  <th className="px-1 text-right font-normal">₹ CR</th>
                  <th className="text-left font-normal">WHY</th>
                </tr>
              </thead>
              <tbody>
                {panel.rejections.slice(-6).map((r) => (
                  <tr key={`${r.time}-${r.bank}-${r.side}`}>
                    <td className="text-term-muted">{r.time}</td>
                    <td className="px-1 text-term-text">
                      {r.bank} {r.side}
                    </td>
                    <td className="px-1 text-right">{croreCount(r.amount)}</td>
                    <td className="text-term-muted">{r.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      <TeachNote code="CALL" />
    </div>
  );
}
