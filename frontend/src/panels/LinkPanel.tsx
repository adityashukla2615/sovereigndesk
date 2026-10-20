import { useMemo } from 'react';

import { LazyChart as Chart } from '../components/LazyChart';
import { inrCr, pct } from '../lib/format';
import { palette } from '../lib/palette';
import { type LinkNode, type LinkPanelData, type LinkResponse, isLinkPanel } from '../market/types';
import { type Slot, useMarket } from '../store/market';
import { send } from '../ws/session';
import { linkOption } from './linkOptions';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

const RESPONSE_CODES: Record<LinkResponse, string> = {
  none: 'NONE',
  vrr: 'VRR',
  omo: 'OMO',
  swap: 'SWAP',
  hike: 'HIKE',
};

function shown(node: LinkNode): string {
  const v = node.value;
  if (!Number.isFinite(v)) return '—';
  const sign = v > 0 ? '+' : v < 0 ? '−' : '';
  const size = Math.abs(v);
  switch (node.unit) {
    case 'US$ bn':
      return `${sign}$${size.toFixed(2)}bn`;
    case '₹ cr':
      return v === 0 ? '₹0' : `${sign}${inrCr(size)}`;
    case '%':
      return `${sign}${size.toFixed(2)}%`;
    default:
      return `${sign}${size.toFixed(size < 10 ? 1 : 0)} bp`;
  }
}

/** One node of the chain. A new run lights the nodes up one after another, along the chain. */
function Node({ node, index, runKey }: { node: LinkNode; index: number; runKey: string }) {
  const tone = node.value < 0 ? 'text-term-down' : node.value > 0 ? 'text-term-up' : 'text-term-text';
  return (
    <div
      key={runKey}
      aria-label={`${node.label}: ${shown(node)}`}
      className="link-node flex min-w-0 flex-col rounded-sm border border-term-line px-1.5 py-0.5"
      style={{ animationDelay: `${String(index * 120)}ms` }}
    >
      <span className="truncate text-[10px] tracking-wider text-term-muted">{node.label.toUpperCase()}</span>
      <span className="flex min-w-0 items-baseline gap-1.5">
        <span className={`shrink-0 text-sm ${tone}`}>{shown(node)}</span>
        <span className="truncate text-[10px] text-term-muted" title={node.detail}>
          {node.detail}
        </span>
      </span>
    </div>
  );
}

function Chain({ panel }: { panel: LinkPanelData }) {
  const runKey = `${panel.mode}-${panel.response}-${String(panel.nodes[0]?.value ?? 0)}-${panel.progress.dates?.[0] ?? ''}`;
  return (
    <ol className="grid grid-cols-3 gap-x-4 gap-y-1.5" aria-label="transmission chain">
      {panel.nodes.map((node, i) => (
        <li key={node.key} className="relative min-w-0">
          <Node node={node} index={i} runKey={runKey} />
          {i < panel.nodes.length - 1 && i % 3 !== 2 && (
            <span
              aria-hidden
              className="link-arrow absolute top-1/2 -right-3.5 -translate-y-1/2 text-xs text-term-amber"
              style={{ animationDelay: `${String(i * 120 + 60)}ms` }}
            >
              →
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}

/** LINK: a US shock followed through FPI flows, the rupee, RBI and rupee liquidity to WACR. */
export function LinkPanel({ slot }: { slot: Slot }) {
  const fx = useMarket((s) => s.india?.fx ?? null);
  const today = useMarket((s) => s.india?.time.slice(0, 10) ?? null);
  const surplus = useMarket((s) => s.india?.surplus_pct ?? null);
  const wacr = useMarket((s) => s.india?.wacr ?? null);
  const data = slot.replies.LINK?.data;
  const panel = isLinkPanel(data) ? data : null;
  // How far the simulation has got: the run's business days up to today's Indian date.
  const dates = panel?.progress.dates ?? null;
  const elapsed = dates && today ? dates.filter((d) => d <= today).length : (panel?.progress.day ?? 0);
  const option = useMemo(() => (panel ? linkOption(panel, palette(), elapsed) : null), [panel, elapsed]);
  if (!panel) return <Waiting what="the linkage (type LINK; the first calibration takes a moment)" />;
  const inr = fx?.inr ?? panel.live.inr;
  const reserves = fx?.reserves_bn ?? panel.live.reserves_bn;
  const p = panel.progress;
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      <StatRow>
        <Stat label={panel.mode === 'run' ? 'US SHOCK' : 'PREVIEW'} tone="text-term-amber">
          {panel.mode === 'run' ? `day ${String(elapsed)} of ${String(p.days)}` : 'Fed +25 bp'}
        </Stat>
        <Stat label="RUPEE">₹{inr.toFixed(2)}/$</Stat>
        <Stat label="RESERVES">${reserves.toFixed(1)}bn</Stat>
        <Stat label="SURPLUS">{surplus === null ? '—' : `${surplus.toFixed(2)}% NDTL`}</Stat>
        <Stat label="WACR">{pct(wacr)}</Stat>
      </StatRow>
      <Chain panel={panel} />
      <div className="flex flex-wrap items-center gap-1 text-[10px]" role="group" aria-label="RBI's response">
        <span className="text-term-muted">RESPONSE</span>
        {panel.responses.map((r) => (
          <button
            key={r}
            type="button"
            title={panel.response_labels[r]}
            onClick={() => {
              send({ op: 'command', text: r === 'none' ? 'LINK' : `LINK ${RESPONSE_CODES[r]}` });
            }}
            className={`rounded-sm border px-1 ${r === panel.response ? 'border-term-amber text-term-amber' : 'border-term-line text-term-text hover:border-term-amber'}`}
          >
            {RESPONSE_CODES[r]}
          </button>
        ))}
        <button
          type="button"
          onClick={() => {
            const answer = panel.response === 'none' ? '' : ` ${RESPONSE_CODES[panel.response]}`;
            send({ op: 'command', text: `SHOCK FED 50BP${answer}` });
          }}
          className="ml-2 rounded-sm border border-term-amber px-1 text-term-amber hover:bg-term-amber/20"
        >
          RUN SHOCK FED 50BP
        </button>
      </div>
      <div className="grid min-h-0 min-w-0 flex-1 grid-cols-2 gap-3">
        <div className="min-h-32">
          {option && <Chart option={option} label="FPI flows, RBI's dollar trades and liquidity by day" />}
        </div>
        <table className="h-fit text-[10px]" aria-label="calibration">
          <thead>
            <tr className="text-term-muted">
              <th className="text-left font-normal">LINK (CALIBRATED)</th>
              <th className="px-1 font-normal">USED</th>
              <th className="px-1 font-normal">90% CI</th>
              <th className="px-1 font-normal">N</th>
            </tr>
          </thead>
          <tbody>
            {panel.estimates.map((e) => (
              <tr key={e.key} title={`${e.method}; ${e.sample}`}>
                <td className="text-term-muted">{e.label}</td>
                <td className="px-1 text-right text-term-text">{e.used.toFixed(2)}</td>
                <td className="px-1 text-right text-term-muted">
                  {e.low === null || e.high === null ? '—' : `${e.low.toFixed(2)}…${e.high.toFixed(2)}`}
                </td>
                <td className="px-1 text-right text-term-muted">{e.n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <TeachNote code="LINK" />
    </div>
  );
}
