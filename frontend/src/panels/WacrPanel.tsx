import { useMemo } from 'react';

import { LazyChart as Chart } from '../components/LazyChart';
import { Corridor } from '../components/Corridor';
import { bp, inrCr, pct } from '../lib/format';
import { palette } from '../lib/palette';
import { isCorridorPanel } from '../market/types';
import { type Slot, useMarket } from '../store/market';
import { macroMapOption, wacrHistoryOption } from './options';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

/** WACR: India's call rate inside RBI's corridor, the fitted macro map and real history. */
export function WacrPanel({ slot }: { slot: Slot }) {
  const india = useMarket((s) => s.india);
  const data = slot.replies.WACR?.data;
  const panel = isCorridorPanel(data) ? data : null;
  // Re-plot only on visible moves: 0.001 point of surplus, 0.1 bp of WACR, or a policy change.
  const repo = india?.corridor.repo ?? null;
  const sdf = india?.corridor.sdf ?? null;
  const msf = india?.corridor.msf ?? null;
  const surplus = india ? Math.round(india.surplus_pct * 1e3) / 1e3 : null;
  const wacr = india ? Math.round(india.wacr * 1e5) / 1e5 : null;
  const mapOption = useMemo(() => {
    if (!panel || repo === null || sdf === null || msf === null) return null;
    const now = surplus !== null && wacr !== null ? { surplus_pct: surplus, wacr } : null;
    return macroMapOption(panel.map, { sdf, repo, msf }, now, palette());
  }, [panel, repo, sdf, msf, surplus, wacr]);
  const history = useMemo(() => (panel ? wacrHistoryOption(panel, palette()) : null), [panel]);
  if (!india) return <Waiting what="the India market" />;
  const c = india.corridor;
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <Corridor
        title="RBI LAF corridor"
        floor={{ label: 'SDF', rate: c.sdf }}
        ceiling={{ label: 'MSF', rate: c.msf }}
        marks={[{ label: 'REPO', rate: c.repo }]}
        value={{ label: 'WACR', rate: india.wacr }}
        target={{ label: 'map', rate: india.map_rate }}
      />
      <StatRow>
        <Stat label="WACR − REPO">{bp(india.wacr - c.repo)}</Stat>
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
        <Stat label="T-BILL 3M">{pct(india.tbills['3M'])}</Stat>
        <Stat label="CRR">
          {(india.crr * 100).toFixed(2)}%
          {india.pending_crr
            ? ` → ${(india.pending_crr.crr * 100).toFixed(2)}% from ${india.pending_crr.from}`
            : ''}
        </Stat>
      </StatRow>
      <div className="grid min-h-40 flex-1 grid-cols-2 gap-2">
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
