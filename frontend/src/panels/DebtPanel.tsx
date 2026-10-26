import { useMemo, useState } from 'react';

import { LazyTimeChart as TimeChart } from '../components/LazyTimeChart';
import { usdBn } from '../lib/format';
import { palette } from '../lib/palette';
import { isDebtPanel } from '../market/types';
import type { Slot } from '../store/market';
import { send } from '../ws/session';
import { Stat, StatRow, TeachNote, Waiting } from './parts';
import { DEBT_MEASURES as MEASURES, type DebtMeasure as Measure, debtChart } from './timeCharts';

/** DEBT: what the simulated curve does to the federal interest bill over ten years, against
 * today's curve held flat, as the debt rolls over and new deficits are funded. */
export function DebtPanel({ slot }: { slot: Slot }) {
  const data = slot.replies.DEBT?.data;
  const panel = isDebtPanel(data) ? data : null;
  const [measure, setMeasure] = useState<Measure>('usd');
  const chart = useMemo(() => (panel ? debtChart(panel, measure, palette()) : null), [panel, measure]);
  if (!panel || !chart) return <Waiting what="the interest bill (type DEBT)" />;
  const at = (k: number) => ({
    base: panel.baseline_interest[k] ?? Number.NaN,
    shock: panel.shocked_interest[k] ?? Number.NaN,
    gdp: (panel.shocked_to_gdp[k] ?? Number.NaN) * 100,
    receipts: (panel.shocked_to_receipts[k] ?? Number.NaN) * 100,
  });
  const year1 = at(11);
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      <StatRow>
        <Stat label="AFTER 1 YEAR">
          {usdBn(year1.shock)}/yr vs {usdBn(year1.base)}
        </Stat>
        {Object.entries(panel.delta_by_year).map(([years, delta]) => (
          <Stat key={years} label={`EXTRA COST, YEAR ${years}`} tone={delta > 0 ? 'text-term-down' : 'text-term-up'}>
            {delta >= 0 ? '+' : ''}
            {usdBn(delta)}/yr
          </Stat>
        ))}
        <Stat label="YEAR 1, SHARE OF">
          GDP {year1.gdp.toFixed(2)}% · receipts {year1.receipts.toFixed(1)}%
        </Stat>
        <Stat label="DEBT AS OF">{panel.start}</Stat>
      </StatRow>
      <div className="flex items-center gap-1 text-[10px]" role="group" aria-label="measure">
        {(Object.keys(MEASURES) as Measure[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => {
              setMeasure(m);
            }}
            className={`rounded-sm border px-1 ${m === measure ? 'border-term-amber text-term-amber' : 'border-term-line text-term-muted'}`}
          >
            {MEASURES[m].label}
          </button>
        ))}
        <span className="mx-1 text-term-line">|</span>
        {chart.lines.map((l) => (
          <span key={l.name} className="flex items-center gap-1 text-term-muted">
            <span
              className={`inline-block w-3 border-t-2 ${l.dashed ? 'border-dashed' : ''}`}
              style={{ borderColor: l.colour }}
            />
            {l.name}
          </span>
        ))}
        <button
          type="button"
          aria-label="recompute on the current curve"
          onClick={() => {
            send({ op: 'command', text: 'DEBT' });
          }}
          className="ml-auto rounded-sm border border-term-line px-1 text-term-amber hover:border-term-amber"
        >
          ↻
        </button>
      </div>
      <div className="min-h-40 flex-1">
        <TimeChart data={chart} label={`Federal interest cost, ${MEASURES[measure].unit}`} />
      </div>
      <TeachNote code="DEBT" />
    </div>
  );
}
