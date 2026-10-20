import { useMemo } from 'react';

import { LazyChart as Chart } from '../components/LazyChart';
import { QualityBadge } from '../components/QualityBadge';
import { bp, pct } from '../lib/format';
import type { Nss } from '../lib/nss';
import { palette } from '../lib/palette';
import { type Curve, GSEC_TENORS, GSEC_YEARS, isGsecPanel } from '../market/types';
import { type Slot, useMarket } from '../store/market';
import { gsecCurveOption, passThroughOption } from './gsecOptions';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

const NSS_KEYS = ['beta0', 'beta1', 'beta2', 'beta3', 'tau1', 'tau2'] as const;

/** Points and NSS parameters as one string, so the chart redraws on visible moves only. */
function curveKey(points: Curve, nss: Nss): string {
  return [
    ...GSEC_TENORS.map((t) => (points[t] ?? 0).toFixed(5)),
    ...NSS_KEYS.map((k) => nss[k].toPrecision(8)),
  ].join(',');
}

function fromKey(key: string): { points: Curve; nss: Nss } {
  const values = key.split(',').map(Number);
  const points = Object.fromEntries(GSEC_TENORS.map((t, i) => [t, values[i] ?? 0]));
  const at = (i: number) => values[GSEC_TENORS.length + i] ?? 0;
  return {
    points,
    nss: { beta0: at(0), beta1: at(1), beta2: at(2), beta3: at(3), tau1: at(4), tau2: at(5) },
  };
}

/** GSEC: India's G-sec curve with its live NSS fit, and how a repo surprise passes through it. */
export function GsecPanel({ slot }: { slot: Slot }) {
  const gsec = useMarket((s) => s.india?.gsec ?? null);
  const repo = useMarket((s) => s.india?.corridor.repo ?? null);
  const data = slot.replies.GSEC?.data;
  const panel = isGsecPanel(data) ? data : null;
  const key = gsec ? curveKey(gsec.points, gsec.nss) : '';
  const curveOption = useMemo(() => {
    if (!key) return null;
    const { points, nss } = fromKey(key);
    return gsecCurveOption(panel?.tenors ?? GSEC_YEARS, points, nss, panel?.close ?? null, palette());
  }, [key, panel]);
  const passOption = useMemo(
    () => (panel ? passThroughOption(panel.passthrough, palette()) : null),
    [panel],
  );
  if (!gsec) return <Waiting what="the G-sec curve" />;
  const points = gsec.points;
  const close = panel?.close;
  const shown = (tenor: string, label: string) => {
    const now = points[tenor];
    const then = close?.[tenor];
    return (
      <Stat label={label}>
        {pct(now, 3)}
        {now !== undefined && then !== undefined ? ` (${bp(now - then, 1)})` : ''}
      </Stat>
    );
  };
  const ten = points['10Y'];
  const two = points['2Y'];
  const pt = panel?.passthrough;
  const beta = (years: number) => pt?.curve.find((r) => Math.abs(r.years - years) < 1e-9)?.beta;
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      <StatRow>
        {shown('3M', '91D T-BILL')}
        {shown('2Y', '2Y')}
        {shown('10Y', '10Y')}
        {shown('30Y', '30Y')}
        {ten !== undefined && repo !== null && <Stat label="10Y − REPO">{bp(ten - repo)}</Stat>}
        {ten !== undefined && two !== undefined && <Stat label="2s10s">{bp(ten - two)}</Stat>}
        <Stat label="NSS FIT">{gsec.rmse_bp.toFixed(1)} bp</Stat>
        <Stat label="FBIL CLOSE">
          <span className="flex items-center gap-1.5" title="FBIL's par yields; the bills are FBIL's T-bill benchmarks">
            {gsec.as_of}
            {gsec.stale && <QualityBadge labels={[gsec.stale]} />}
          </span>
        </Stat>
        {pt && (
          <Stat label="β PER UNIT OF SURPRISE">
            <span
              title={`κ ${pt.kappa.toFixed(2)}/yr (half-life ${pt.half_life_years.toFixed(1)}y), term premium γ ${pt.gamma.toFixed(2)}; 10Y band ${(pt.beta_10y_band[0] ?? 0).toFixed(2)}–${(pt.beta_10y_band[1] ?? 0).toFixed(2)} from ${String(pt.events.length)} repo changes`}
            >
              2Y {(beta(2) ?? 0).toFixed(2)} · 10Y {(beta(10) ?? 0).toFixed(2)}
            </span>
          </Stat>
        )}
      </StatRow>
      <div className="grid min-h-40 min-w-0 flex-1 grid-cols-2 gap-2">
        {curveOption && <Chart option={curveOption} label="G-sec curve: market points and NSS fit" />}
        {passOption ? (
          <Chart option={passOption} label="Repo pass-through by maturity: event study and fit" />
        ) : (
          <Waiting what="the event study (type GSEC)" />
        )}
      </div>
      <TeachNote code="GSEC" />
    </div>
  );
}
