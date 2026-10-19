import type { ReactNode } from 'react';

import type { HealthState } from '../api/useHealth';
import { MARKET_ZONES, formatClock } from '../lib/time';
import { useNow } from '../lib/useNow';
import { useConnection } from '../store/connection';
import type { ConnectionStatus } from '../ws/client';

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

export function StatusStrip({ health }: { health: HealthState }) {
  const status = useConnection((s) => s.status);
  const gaps = useConnection((s) => s.gaps);
  const now = useNow();
  const ws = WS_STATUS[status];

  return (
    <div
      role="status"
      aria-label="system status"
      className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-term-line bg-term-panel px-3 py-1 text-xs"
    >
      <Field label="WS">
        <span className={ws.className}>● {ws.text}</span>
      </Field>
      <ApiFields health={health} />
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
