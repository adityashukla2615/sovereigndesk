import { useState } from 'react';

import { type MpcModelName, type MpcPanelData, isMpcPanel } from '../market/types';
import { pct } from '../lib/format';
import type { Slot } from '../store/market';
import { send } from '../ws/session';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

const MODELS: { key: MpcModelName; label: string }[] = [
  { key: 'ordered logit', label: 'ORDERED LOGIT' },
  { key: 'xgboost', label: 'XGBOOST' },
  { key: 'taylor', label: 'TAYLOR RULE' },
];
const BASELINES = ['repeat last', 'always hold'];
const SHORT = ['BIG CUT', 'CUT', 'HOLD', 'HIKE', 'BIG HIKE'];

function daysUntil(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

function value(v: number | null, digits = 2): string {
  return v === null ? '—' : v.toFixed(digits);
}

/** One model's probability for each class, as horizontal bars. */
function Bars({ probabilities, label }: { probabilities: number[]; label: string }) {
  const best = probabilities.indexOf(Math.max(...probabilities));
  return (
    <div className="flex min-w-0 flex-col gap-0.5" aria-label={`${label} probabilities`}>
      <span className="text-[10px] tracking-wider text-term-muted">{label}</span>
      {probabilities.map((p, k) => (
        <div key={SHORT[k]} className="flex items-center gap-1.5 text-[11px]">
          <span className="w-16 shrink-0 text-term-muted">{SHORT[k]}</span>
          <span className="relative h-2.5 min-w-0 flex-1 bg-term-panel">
            <span
              className={`absolute inset-y-0 left-0 ${k === best ? 'bg-term-amber' : 'bg-term-accent/60'}`}
              style={{ width: `${String(Math.round(p * 100))}%` }}
            />
          </span>
          <span className={`w-9 text-right ${k === best ? 'text-term-amber' : 'text-term-text'}`}>
            {(p * 100).toFixed(0)}%
          </span>
        </div>
      ))}
    </div>
  );
}

function Confusion({ panel, model }: { panel: MpcPanelData; model: string }) {
  const matrix = panel.backtest.models[model]?.confusion ?? [];
  const most = Math.max(1, ...matrix.flat());
  return (
    <table className="text-[10px]" aria-label={`${model} confusion matrix`}>
      <thead>
        <tr>
          <th className="pr-1 text-left font-normal text-term-muted">actual ↓ / called →</th>
          {SHORT.map((c) => (
            <th key={c} className="px-1 font-normal text-term-muted">
              {c.replace('BIG ', 'B.')}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {matrix.map((row, a) => (
          <tr key={SHORT[a]}>
            <td className="pr-1 text-term-muted">{SHORT[a]}</td>
            {row.map((n, p) => (
              <td
                key={SHORT[p]}
                className={`px-1 text-center ${a === p ? 'text-term-up' : 'text-term-text'}`}
                style={{ backgroundColor: n ? `rgba(255, 176, 0, ${String(0.08 + (0.5 * n) / most)})` : undefined }}
              >
                {n || ''}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** MPC: the next decision's probabilities by model, the walk-forward backtest, the features. */
export function MpcPanel({ slot }: { slot: Slot }) {
  const [model, setModel] = useState<MpcModelName>('ordered logit');
  const data = slot.replies.MPC?.data;
  const panel = isMpcPanel(data) ? data : null;
  if (!panel) return <Waiting what="the MPC predictor (type MPC; the first fit takes a few seconds)" />;
  const logit = panel.probabilities['ordered logit'];
  const best = logit.indexOf(Math.max(...logit));
  const reports = panel.backtest.models;
  const t = panel.taylor;
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      <StatRow>
        <Stat label="NEXT MEETING">
          {panel.next_meeting ?? '—'}
          {panel.next_meeting ? ` (in ${String(daysUntil(panel.as_of, panel.next_meeting))}d)` : ''}
        </Stat>
        <Stat label="MOST LIKELY (LOGIT)" tone="text-term-amber">
          {panel.classes[best]?.toUpperCase()} {((logit[best] ?? 0) * 100).toFixed(0)}%
        </Stat>
        <Stat label="TAYLOR RATE">
          {pct(t.prescribed)} vs repo {pct(t.repo)}
        </Stat>
        <Stat label="SAMPLE">
          {String(panel.sample.decisions)} decisions {panel.sample.first.slice(0, 4)}–{panel.sample.last.slice(0, 4)}
        </Stat>
        <Stat label="AS OF">
          <button
            type="button"
            title="Refit-free refresh: today's features from the data and the simulation"
            onClick={() => {
              send({ op: 'command', text: 'MPC' });
            }}
            className="rounded-sm border border-term-line px-1 text-xs text-term-amber hover:border-term-amber"
          >
            {panel.as_of} ↻
          </button>
        </Stat>
      </StatRow>
      <div className="grid min-h-0 min-w-0 flex-1 grid-cols-3 gap-3 overflow-auto">
        <div className="flex min-w-0 flex-col gap-2">
          {MODELS.map((m) => (
            <Bars key={m.key} label={m.label} probabilities={panel.probabilities[m.key]} />
          ))}
        </div>
        <div className="flex min-w-0 flex-col gap-2">
          <table className="text-[11px]" aria-label="backtest">
            <thead>
              <tr className="text-term-muted">
                <th className="text-left font-normal">
                  {String(panel.backtest.forecasts)} forecasts from {panel.backtest.first}
                </th>
                <th className="px-1 font-normal">HIT</th>
                <th className="px-1 font-normal">F1</th>
                <th className="px-1 font-normal">BRIER</th>
              </tr>
            </thead>
            <tbody>
              {[...MODELS.map((m) => m.key as string), ...BASELINES].map((name) => {
                const r = reports[name];
                if (!r) return null;
                const selectable = MODELS.some((m) => m.key === name);
                return (
                  <tr key={name} className={name === model ? 'text-term-amber' : 'text-term-text'}>
                    <td>
                      {selectable ? (
                        <button
                          type="button"
                          onClick={() => {
                            setModel(name as MpcModelName);
                          }}
                          className="hover:text-term-amber"
                        >
                          {name}
                        </button>
                      ) : (
                        <span className="text-term-muted">{name}</span>
                      )}
                    </td>
                    <td className="px-1 text-right">{(r.accuracy * 100).toFixed(0)}%</td>
                    <td className="px-1 text-right">{r.macro_f1.toFixed(2)}</td>
                    <td className="px-1 text-right">{r.brier.toFixed(2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Confusion panel={panel} model={model} />
        </div>
        <table className="h-fit text-[11px]" aria-label="features">
          <thead>
            <tr className="text-term-muted">
              <th className="text-left font-normal">FEATURE</th>
              <th className="px-1 font-normal">NOW</th>
              <th className="px-1 font-normal">LAST MPC</th>
            </tr>
          </thead>
          <tbody>
            {panel.features.map((f) => (
              <tr key={f.key}>
                <td className="text-term-muted">{f.label}</td>
                <td className="px-1 text-right text-term-text">{value(f.now)}</td>
                <td className="px-1 text-right text-term-muted">{value(f.last)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <TeachNote code="MPC" />
    </div>
  );
}
