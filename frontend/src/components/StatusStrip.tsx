import type { ReactNode } from 'react';

import type { HealthState } from '../api/useHealth';
import type { SimStatus } from '../api/useSim';
import { simClock } from '../lib/corridor';
import { STATIC_DEMO } from '../lib/staticDemo';
import { MARKET_ZONES, formatClock } from '../lib/time';
import { useNow } from '../lib/useNow';
import { useConnection } from '../store/connection';
import { useMarket } from '../store/market';
import type { ConnectionStatus } from '../ws/client';
import { QualityBadge } from './QualityBadge';

const WS_STATUS: Record<ConnectionStatus, { text: string; className: string }> = {
  open: { text: 'LIVE', className: 'text-term-up' },
  connecting: { text: 'CONNECTING', className: 'text-term-amber animate-pulse' },
  closed: { text: 'DOWN', className: 'text-term-down' },
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-term-muted">{label}</span>
      <span className="text-term-text">{children}</span>
    </span>
  );
}

function ApiFields({ health }: { health: HealthState }) {
  switch (health.kind) {
    case 'loading':
      return <Field label="API">…</Field>;
    case 'down':
      return (
        <Field label="API">
          <span className="text-term-down" title={health.error}>
            DOWN
          </span>
        </Field>
      );
    case 'ok': {
      const { version, engine_version, offline, fred_key_configured } = health.health;
      if (STATIC_DEMO) {
        return (
          <>
            <Field label="ENGINE">v{engine_version}</Field>
            <Field label="MODE">
              <span className="text-term-amber">STATIC DEMO · RECORDED ON THE SEED</span>
            </Field>
          </>
        );
      }
      return (
        <>
          <Field label="API">v{version}</Field>
          <Field label="ENGINE">v{engine_version}</Field>
          <Field label="FRED">
            {fred_key_configured ? 'KEY OK' : <span className="text-term-down">NO KEY</span>}
          </Field>
          <Field label="MODE">
            {offline ? <span className="text-term-amber">OFFLINE · SEED</span> : 'ONLINE'}
          </Field>
        </>
      );
    }
  }
}

function SimFields({ sim }: { sim: SimStatus | null }) {
  const simTime = useMarket((s) => s.us?.sim_time ?? s.india?.sim_time ?? null);
  if (!sim) return null;
  return (
    <>
      <Field label="SIM">
        {sim.paused ? <span className="text-term-down">PAUSED</span> : `${String(sim.speed)}×`}
      </Field>
      {simTime && (
        <Field label="SIM TIME">
          {simClock(simTime, 'Asia/Kolkata')} IST · {simClock(simTime, 'America/New_York').slice(-5)} ET
        </Field>
      )}
      <span className="flex items-center gap-1.5">
        {sim.running ? (
          <QualityBadge prefix="US" labels={sim.input_quality} />
        ) : (
          <span className="text-term-down" title={sim.error ?? undefined}>
            US DOWN
          </span>
        )}
        {sim.india.running ? (
          <QualityBadge prefix="IN" labels={sim.india.input_quality} />
        ) : (
          <span className="text-term-down" title={sim.india.error ?? undefined}>
            IN DOWN
          </span>
        )}
      </span>
    </>
  );
}

export function StatusStrip({ health, sim = null }: { health: HealthState; sim?: SimStatus | null }) {
  const status = useConnection((s) => s.status);
  const gaps = useConnection((s) => s.gaps);
  const now = useNow();
  const ws =
    STATIC_DEMO && status === 'open' ? { text: 'PLAYBACK', className: 'text-term-amber' } : WS_STATUS[status];

  return (
    <div
      role="status"
      aria-label="system status"
      className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-term-line bg-term-panel px-3 py-1 text-xs"
    >
      <Field label={STATIC_DEMO ? 'DATA' : 'WS'}>
        <span className={ws.className}>● {ws.text}</span>
      </Field>
      <ApiFields health={health} />
      <SimFields sim={sim} />
      {gaps > 0 && (
        <Field label="GAPS">
          <span className="text-term-down">{gaps}</span>
        </Field>
      )}
      <span className="ml-auto flex gap-4">
        {MARKET_ZONES.map((zone) => (
          <Field key={zone.label} label={zone.label}>
            <time dateTime={now.toISOString()}>{formatClock(now, zone.timeZone)}</time>
          </Field>
        ))}
      </span>
    </div>
  );
}
