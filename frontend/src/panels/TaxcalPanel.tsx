import { useMemo } from 'react';

import { LazyChart as Chart } from '../components/LazyChart';
import { LazyTimeChart as TimeChart } from '../components/LazyTimeChart';
import { inrCr } from '../lib/format';
import { palette } from '../lib/palette';
import { type TaxProjection, isTaxcalPanel } from '../market/types';
import type { Slot } from '../store/market';
import { taxChart } from './timeCharts';
import { Stat, StatRow, TeachNote, Waiting } from './parts';
import { taxHeatmapOption, taxWindows } from './taxcalOptions';

function span(first: string, last: string): string {
  return first === last ? first : `${first} → ${last.slice(5)}`;
}

/** TAXCAL: the quarterly liquidity cycle. A calendar of WACR − repo by day; the government's
 * tax balance at RBI against the system's surplus, simulated and then projected from tax flows
 * alone; RBI's auctions in answer; and the tax windows ahead. */
export function TaxcalPanel({ slot }: { slot: Slot }) {
  const data = slot.replies.TAXCAL?.data;
  const panel = isTaxcalPanel(data) ? data : null;
  const heatmap = useMemo(() => (panel ? taxHeatmapOption(panel, palette()) : null), [panel]);
  const cycle = useMemo(() => (panel ? taxChart(panel, palette()) : null), [panel]);
  const windows = useMemo(() => (panel ? taxWindows(panel) : []), [panel]);
  if (!panel || !heatmap || !cycle) return <Waiting what="the tax calendar (type TAXCAL)" />;
  const low = panel.projection.reduce<TaxProjection | null>(
    (worst, d) => (worst === null || d.surplus < worst.surplus ? d : worst),
    null,
  );
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      <StatRow>
        <Stat label="ADVANCE TAX (MEDIAN)">{inrCr(panel.tax.advance_tax_drain)}</Stat>
        <Stat label="GST (MEDIAN)">{inrCr(panel.tax.gst_drain)}</Stat>
        <Stat label="GOVT TAX BALANCE AT RBI">
          {panel.now.government >= 0 ? '+' : ''}
          {inrCr(panel.now.government)} since the anchor
        </Stat>
        <Stat label="SURPLUS NOW">
          {inrCr(panel.now.surplus)} · {panel.now.surplus_pct.toFixed(2)}% NDTL
        </Stat>
        {low && (
          <Stat label={`TIGHTEST AHEAD (${low.date})`} tone={low.surplus < 0 ? 'text-term-down' : undefined}>
            {inrCr(low.surplus)} · VRR {(low.p_vrr * 100).toFixed(0)}% likely
          </Stat>
        )}
      </StatRow>
      <div className="grid min-h-48 min-w-0 flex-1 grid-cols-2 grid-rows-[minmax(0,1fr)] gap-2">
        <div className="flex min-h-0 min-w-0 flex-col">
          <span className="text-[10px] text-term-muted">WACR − REPO BY DAY: RBI DATA, THEN SIMULATED (● ADVANCE TAX DUE)</span>
          <div className="min-h-0 flex-1">
            <Chart option={heatmap} label="Calendar heatmap of WACR minus repo by day" />
          </div>
        </div>
        <div className="flex min-h-0 min-w-0 flex-col">
          <span className="text-[10px] text-term-muted">
            ₹ LAKH CR: SIMULATED TO TODAY, THEN TAX FLOWS ALONE (VRR? = LIKELIER THAN NOT)
          </span>
          <div className="flex flex-wrap gap-x-2 text-[10px] text-term-muted" aria-label="legend">
            {cycle.lines.map((l) => (
              <span key={l.name} className="flex items-center gap-1">
                <span className="inline-block w-3 border-t-2" style={{ borderColor: l.colour }} />
                {l.name}
              </span>
            ))}
          </div>
          <div className="min-h-0 flex-1">
            <TimeChart data={cycle} label="Government's tax balance at RBI against the system's surplus" />
          </div>
        </div>
      </div>
      <table className="text-[10px]" aria-label="tax windows ahead">
        <thead>
          <tr className="text-term-muted">
            <th className="text-left font-normal">AHEAD</th>
            <th className="px-1 text-left font-normal">DAYS</th>
            <th className="px-1 text-right font-normal">EXPECTED DRAIN</th>
          </tr>
        </thead>
        <tbody>
          {windows.slice(0, 5).map((w) => (
            <tr key={`${w.kind}-${w.first}`}>
              <td className={w.kind === 'Advance tax' ? 'text-term-amber' : 'text-term-text'}>{w.kind}</td>
              <td className="px-1">{span(w.first, w.last)}</td>
              <td className="px-1 text-right">{inrCr(w.drain)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[10px] text-term-muted">
        Receipts stay in the government&apos;s account about {String(panel.tax.hold_days)} days, then come back
        over {String(panel.tax.return_days)} as it spends ({String(panel.tax.events)} episodes in RBI&apos;s
        data). The balance is the change from tax flows since the anchor: its level is not in the data.
      </p>
      <TeachNote code="TAXCAL" />
    </div>
  );
}
