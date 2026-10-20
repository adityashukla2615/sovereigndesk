import { useMemo } from 'react';

import { Corridor } from '../components/Corridor';
import { LazyChart as Chart } from '../components/LazyChart';
import { QualityBadge } from '../components/QualityBadge';
import { bp, inrCr, pct } from '../lib/format';
import { palette } from '../lib/palette';
import { isCorridorPanel } from '../market/types';
import { type Slot, useMarket } from '../store/market';
import { send } from '../ws/session';
import { macroMapOption, wacrHistoryOption } from './options';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

/** WACR: India's call rate and RBI's corridor, the fitted macro map and real history. */
export function WacrPanel({ slot }: { slot: Slot }) {
  const india = useMarket((s) => s.india);
  const data = slot.replies.WACR?.data;
  const panel = isCorridorPanel(data) ? data : null;
  // Re-plot only on visible moves: 0.001 point of surplus, 0.1 bp of WACR, or a policy change.
  const repo = india?.corridor.repo ?? null;
  const sdf = india?.corridor.sdf ?? null;
  const msf = india?.corridor.msf ?? null;
  const lower = india?.band.lower ?? null;
  const upper = india?.band.upper ?? null;
  const surplus = india ? Math.round(india.surplus_pct * 1e3) / 1e3 : null;
  const wacr = india ? Math.round(india.wacr * 1e5) / 1e5 : null;
  const mapOption = useMemo(() => {
    if (!panel || repo === null || sdf === null || msf === null || lower === null || upper === null) {
      return null;
    }
    const now = surplus !== null && wacr !== null ? { surplus_pct: surplus, wacr } : null;
    return macroMapOption(panel.map, { sdf, repo, msf }, now, palette(), { lower, upper });
  }, [panel, repo, sdf, msf, lower, upper, surplus, wacr]);
  const history = useMemo(() => (panel ? wacrHistoryOption(panel, palette()) : null), [panel]);
  if (!india) return <Waiting what="the India market" />;
  const c = india.corridor;
  const realistic = india.mode === 'realistic';
  const x = panel?.excursions;
  const modeNote = realistic
    ? x
      ? `WACR may leave the corridor as it has: ${String(x.below_sdf)} days below the SDF and ${String(x.above_msf)} above the MSF of ${String(x.trading_days)} since April 2022`
      : 'WACR may leave the corridor as RBI’s data shows it does'
    : 'Call rates are clamped inside RBI’s corridor';
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
        <Stat label="MODE">
          <button
            type="button"
            title={`${modeNote}. Click for ${realistic ? 'policy' : 'realistic'} mode.`}
            onClick={() => {
              send({ op: 'command', text: realistic ? 'WACR POLICY' : 'WACR REALISTIC' });
            }}
            className="rounded-sm border border-term-line px-1 text-xs text-term-amber hover:border-term-amber"
          >
            {realistic ? 'REALISTIC' : 'POLICY'} ⇄
          </button>
        </Stat>
        <Stat
          label="WACR − REPO"
          tone={india.wacr < c.sdf || india.wacr > c.msf ? 'text-term-down' : undefined}
        >
          {bp(india.wacr - c.repo)}
        </Stat>
        <Stat label="SURPLUS">
          {inrCr(india.surplus)} · {india.surplus_pct.toFixed(2)}% NDTL
        </Stat>
        <Stat label="MAP RATE">{pct(india.map_rate)}</Stat>
        <Stat label={india.session_open ? 'CALL TODAY' : 'CALL (CLOSED)'}>
          {inrCr(india.call.volume)}
          {india.call.low !== null && india.call.high !== null
            ? ` · ${pct(india.call.low)}–${pct(india.call.high)}`
            : ''}
        </Stat>
        <Stat label="SDF / MSF LAST NIGHT">
          {inrCr(india.laf.sdf)} / {inrCr(india.laf.msf)}
        </Stat>
        <Stat label="VRRR / VRR OUT">
          {inrCr(india.laf.vrrr)} / {inrCr(india.laf.vrr)}
        </Stat>
        <Stat label="TREPS">{pct(india.segments.treps)}</Stat>
        <Stat label="T-BILL 3M">
          <span className="flex items-center gap-1.5" title={`FBIL benchmark as of ${india.tbills_as_of}`}>
            {pct(india.tbills['3M'])}
            {india.tbills_stale && <QualityBadge labels={[india.tbills_stale]} />}
          </span>
        </Stat>
        <Stat label="CRR">
          {(india.crr * 100).toFixed(2)}%
          {india.pending_crr
            ? ` → ${(india.pending_crr.crr * 100).toFixed(2)}% from ${india.pending_crr.from}`
            : ''}
        </Stat>
      </StatRow>
      <div className="grid min-h-40 min-w-0 flex-1 grid-cols-2 gap-2">
        {mapOption ? (
          <Chart option={mapOption} label="Macro map: WACR against surplus" />
        ) : (
          <Waiting what="the fitted macro map (type WACR)" />
        )}
        {history && <Chart option={history} label="WACR − repo by day, real and simulated" />}
      </div>
      <TeachNote code="WACR" />
    </div>
  );
}
