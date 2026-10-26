import { useEffect, useMemo, useState } from 'react';

import { LazyTimeChart as TimeChart } from '../components/LazyTimeChart';
import { palette } from '../lib/palette';
import { type ReplayPanelData, type ReplayTarget, isReplayPanel } from '../market/types';
import type { Slot } from '../store/market';
import { send } from '../ws/session';
import { annotationIndex, replayChart } from './replayChart';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

const SPEEDS = [1, 3, 10];
const TICK_MS = 120;

function fmt(v: number | null | undefined, digits: number, unit = ''): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}${unit}`;
}

function Scores({ target }: { target: ReplayTarget }) {
  return (
    <table className="text-[10px]" aria-label="replay scores">
      <thead>
        <tr className="text-term-muted">
          <th className="text-left font-normal">MODEL</th>
          <th className="px-1 font-normal">RMSE</th>
          <th className="px-1 font-normal">MAE</th>
          <th className="px-1 font-normal">DIRECTION</th>
          <th className="px-1 font-normal">PEAK (MODEL / ACTUAL)</th>
          <th className="px-1 font-normal">LAG</th>
          <th className="px-1 font-normal">END (MODEL / ACTUAL)</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(target.scores).map(([name, s]) => (
          <tr key={name} className="whitespace-nowrap">
            <td className="text-term-text">{name}</td>
            <td className="px-1 text-right">{s.rmse.toFixed(target.digits)}</td>
            <td className="px-1 text-right">{s.mae.toFixed(target.digits)}</td>
            <td className="px-1 text-right">{s.direction === null ? '—' : `${(s.direction * 100).toFixed(0)}%`}</td>
            <td className="px-1 text-right">
              {fmt(s.peak_model, target.digits)} / {fmt(s.peak_actual, target.digits)}
            </td>
            <td className="px-1 text-right">{String(s.peak_lag)}d</td>
            <td className="px-1 text-right">
              {fmt(s.end_model, target.digits)} / {fmt(s.end_actual, target.digits)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

interface LambdaRow {
  profile: string;
  announcement_day: boolean;
  lam: number;
  low: number;
  high: number;
  r2: number;
  n: number;
}

function isLambdaRows(value: unknown): value is LambdaRow[] {
  return Array.isArray(value) && value.every((r) => typeof r === 'object' && r !== null && 'lam' in r);
}

/** The gilt crisis's λ under every specification (profile of LDI sales × the announcement day). */
function LambdaTable({ facts }: { facts: Record<string, unknown> }) {
  const lam = facts.lambda;
  if (typeof lam !== 'object' || lam === null) return null;
  const rows = (lam as Record<string, unknown>).profiles;
  if (!isLambdaRows(rows)) return null;
  return (
    <table className="text-[10px]" aria-label="lambda specifications">
      <thead>
        <tr className="text-term-muted">
          <th className="text-left font-normal">LDI PROFILE</th>
          <th className="px-1 font-normal">28 SEP</th>
          <th className="px-1 font-normal">λ (BP PER DAY'S TURNOVER)</th>
          <th className="px-1 font-normal">90% CI</th>
          <th className="px-1 font-normal">R²</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr
            key={`${r.profile}-${String(r.announcement_day)}`}
            className={`whitespace-nowrap ${!r.announcement_day && r.profile === 'even' ? 'text-term-amber' : ''}`}
          >
            <td>{r.profile}</td>
            <td className="px-1 text-center">{r.announcement_day ? 'in' : 'out'}</td>
            <td className="px-1 text-right">{r.lam.toFixed(1)}</td>
            <td className="px-1 text-right">
              {r.low.toFixed(0)} … {r.high.toFixed(0)}
            </td>
            <td className="px-1 text-right">{r.r2.toFixed(2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ReplayView({ panel }: { panel: ReplayPanelData }) {
  const [targetKey, setTargetKey] = useState(panel.targets[0]?.key ?? '');
  const target = panel.targets.find((t) => t.key === targetKey) ?? panel.targets[0];
  const last = (target?.dates.length ?? 1) - 1;
  const [cursor, setCursor] = useState(last);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(SPEEDS[0] ?? 1);
  const running = playing && cursor < last;
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => {
      setCursor((c) => Math.min(c + speed, last));
    }, TICK_MS);
    return () => {
      clearInterval(id);
    };
  }, [running, speed, last]);
  const chart = useMemo(
    () => (target ? replayChart(target, cursor, panel.annotations, palette()) : null),
    [target, cursor, panel.annotations],
  );
  if (!target) return <Waiting what="the episode's paths" />;
  const day = target.dates[Math.min(cursor, last)] ?? '';
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-1.5">
      <StatRow>
        <Stat label="REPLAY" tone="text-term-amber">
          {panel.episode.title}
        </Stat>
        <Stat label="WINDOW">
          {panel.episode.start} → {panel.episode.end}
        </Stat>
        <Stat label="DAY">{day}</Stat>
      </StatRow>
      <div className="flex flex-wrap items-center gap-1 text-[10px]" role="group" aria-label="episodes">
        {panel.available.map((e) => (
          <button
            key={e.id}
            type="button"
            title={e.title}
            onClick={() => {
              send({ op: 'command', text: `REPLAY ${e.id}` });
            }}
            className={`rounded-sm border px-1 ${e.id === panel.episode.id ? 'border-term-amber text-term-amber' : 'border-term-line text-term-text hover:border-term-amber'}`}
          >
            {e.id}
          </button>
        ))}
        <span className="mx-1 text-term-line">|</span>
        {panel.targets.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => {
              setTargetKey(t.key);
              setCursor(t.dates.length - 1);
              setPlaying(false);
            }}
            className={`rounded-sm border px-1 ${t.key === target.key ? 'border-term-accent text-term-accent' : 'border-term-line text-term-muted hover:border-term-accent'}`}
          >
            {t.label.toUpperCase()}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2 text-[10px]" role="group" aria-label="playback">
        <button
          type="button"
          onClick={() => {
            if (running) {
              setPlaying(false);
              return;
            }
            if (cursor >= last) setCursor(0);
            setPlaying(true);
          }}
          className="rounded-sm border border-term-amber px-1.5 text-term-amber hover:bg-term-amber/20"
        >
          {running ? 'PAUSE' : 'PLAY'}
        </button>
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              setSpeed(s);
            }}
            className={`rounded-sm border px-1 ${s === speed ? 'border-term-amber text-term-amber' : 'border-term-line text-term-muted'}`}
          >
            {String(s)}×
          </button>
        ))}
        <input
          type="range"
          aria-label="scrub"
          min={0}
          max={last}
          value={cursor}
          onChange={(e) => {
            setPlaying(false);
            setCursor(Number(e.target.value));
          }}
          className="min-w-0 flex-1 accent-term-amber"
        />
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[3fr_2fr] grid-rows-[minmax(0,1fr)] gap-2">
        <div className="flex min-h-40 min-w-0 flex-col gap-0.5">
          <div className="flex flex-wrap gap-x-2 text-[10px] text-term-muted" aria-label="legend">
            {chart?.lines.map((l) => (
              <span key={l.name} className="flex items-center gap-1">
                <span
                  className={`inline-block w-3 border-t-2 ${l.dashed ? 'border-dashed' : ''}`}
                  style={{ borderColor: l.colour }}
                />
                {l.name}
              </span>
            ))}
          </div>
          <div className="min-h-0 flex-1">
            {chart && <TimeChart data={chart} label={`${target.label}: the model against what happened`} />}
          </div>
        </div>
        <div className="flex min-h-0 flex-col gap-1.5 overflow-auto text-[10px]">
          <ul aria-label="what the model got right and wrong" className="list-disc pl-3 text-term-text">
            {target.summary.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <Scores target={target} />
          <LambdaTable facts={panel.facts} />
          <ol aria-label="timeline" className="list-decimal pl-4 text-term-muted">
            {panel.annotations.map((a) => (
              <li key={`${a.date}-${a.text}`}>
                <button
                  type="button"
                  onClick={() => {
                    const k = annotationIndex(target, a.date);
                    if (k >= 0) {
                      setPlaying(false);
                      setCursor(k);
                    }
                  }}
                  className="text-left hover:text-term-amber"
                >
                  <span className="text-term-amber">{a.date}</span> {a.text}
                </button>{' '}
                {a.source.startsWith('https://') ? (
                  <a href={a.source} target="_blank" rel="noreferrer" className="text-term-accent">
                    source
                  </a>
                ) : (
                  <span>({a.source})</span>
                )}
              </li>
            ))}
          </ol>
          {panel.notes.length > 0 && <p className="text-term-muted">{panel.notes.join(' ')}</p>}
        </div>
      </div>
      <TeachNote code="REPLAY" />
    </div>
  );
}

const replayIds = new WeakMap<object, number>();
let nextReplayId = 0;

function keyOf(reply: object): string {
  let id = replayIds.get(reply);
  if (id === undefined) {
    id = nextReplayId++;
    replayIds.set(reply, id);
  }
  return String(id);
}

/** REPLAY: a real episode replayed with the model driven by what actually moved. */
export function ReplayPanel({ slot }: { slot: Slot }) {
  const data = slot.replies.REPLAY?.data;
  if (!isReplayPanel(data)) return <Waiting what="a replay (type REPLAY GILT2022, REPLAY TAPER2013, …)" />;
  return <ReplayView key={keyOf(data)} panel={data} />;
}
