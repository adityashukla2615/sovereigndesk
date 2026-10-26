import { inrCr, pct } from '../lib/format';
import { type CcilPanelData, type CcilSegment, isCcilPanel } from '../market/types';
import type { Slot } from '../store/market';
import { TeachNote, Waiting } from './parts';

const ROW_Y: Record<CcilSegment['key'], number> = { call: 52, treps: 136, market_repo: 206 };

function Box({
  x,
  y,
  w,
  h,
  title,
  lines,
  tone = 'stroke-term-line',
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  lines: string[];
  tone?: string;
}) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={3} className={`fill-term-panel ${tone}`} strokeWidth={1} />
      <text x={x + 6} y={y + 13} className="fill-term-amber" fontSize={10} fontWeight={600}>
        {title}
      </text>
      {lines.map((line, i) => (
        <text key={line} x={x + 6} y={y + 26 + i * 11} className="fill-term-text" fontSize={8.5}>
          {line}
        </text>
      ))}
    </g>
  );
}

function Arrow({ x1, y1, x2, y2, label, dashed = false }: { x1: number; y1: number; x2: number; y2: number; label: string; dashed?: boolean }) {
  return (
    <g>
      <line
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        className="stroke-term-muted"
        strokeWidth={1}
        strokeDasharray={dashed ? '3 2' : undefined}
        markerEnd="url(#ccil-arrow)"
      />
      <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 4} textAnchor="middle" className="fill-term-muted" fontSize={8}>
        {label}
      </text>
    </g>
  );
}

function Diagram({ panel }: { panel: CcilPanelData }) {
  const seg = Object.fromEntries(panel.segments.map((s) => [s.key, s])) as Record<CcilSegment['key'], CcilSegment>;
  const today = (s: CcilSegment) => `${pct(s.rate)} · ${inrCr(s.volume)} today`;
  return (
    <svg
      viewBox="0 0 640 250"
      role="img"
      aria-label="How call money, TREPS and market repo trade and settle"
      className="h-auto w-full max-w-4xl shrink-0"
    >
      <defs>
        <marker id="ccil-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" className="fill-term-muted" />
        </marker>
      </defs>
      <text x={8} y={12} className="fill-term-muted" fontSize={8.5}>
        MEMBERS
      </text>
      <text x={150} y={12} className="fill-term-muted" fontSize={8.5}>
        DEAL (CLEARCORP)
      </text>
      <text x={330} y={12} className="fill-term-muted" fontSize={8.5}>
        CLEAR
      </text>
      <text x={500} y={12} className="fill-term-muted" fontSize={8.5}>
        SETTLE
      </text>
      <Box x={8} y={22} w={110} h={62} title="Banks, PDs" lines={['call money: only', 'banks and primary', 'dealers (RBI)']} />
      <Box x={8} y={104} w={110} h={130} title="Members" lines={['borrow cash against', 'G-secs; the lender', 'holds them until', 'it is repaid']} />
      <Box
        x={150}
        y={22}
        w={150}
        h={62}
        title={`NDS-CALL ${seg.call.hours.join('–')}`}
        lines={['RBI-owned, request for', 'quote, unsecured', today(seg.call)]}
        tone="stroke-term-amber"
      />
      <Box
        x={150}
        y={104}
        w={150}
        h={56}
        title={`TREPS ${seg.treps.hours.join('–')}`}
        lines={['tri-party repo, anonymous', today(seg.treps)]}
        tone="stroke-term-accent"
      />
      <Box
        x={150}
        y={176}
        w={150}
        h={56}
        title={`CROMS ${seg.market_repo.hours.join('–')}`}
        lines={['market repo, anonymous', today(seg.market_repo)]}
        tone="stroke-term-accent"
      />
      <text x={310} y={70} className="fill-term-down" fontSize={8.5}>
        no central counterparty: each
      </text>
      <text x={310} y={81} className="fill-term-down" fontSize={8.5}>
        lender carries its borrower&apos;s risk
      </text>
      <Box
        x={330}
        y={112}
        w={124}
        h={112}
        title="CCIL"
        lines={['central counterparty:', 'novates each trade,', 'nets every member’s', 'funds and securities,', 'guarantees settlement;', 'TREPS: tri-party agent']}
        tone="stroke-term-up"
      />
      <Box x={500} y={22} w={132} h={62} title="RBI RTGS" lines={['bank to bank,', 'trade by trade,', 'during the day']} />
      <Box x={500} y={112} w={132} h={46} title="RBI" lines={['funds, net, in each', 'member’s account']} />
      <Box x={500} y={176} w={132} h={48} title="GILT accounts at CCIL" lines={['securities, from', 'borrower to lender']} />
      <Arrow x1={118} y1={ROW_Y.call} x2={150} y2={ROW_Y.call} label="" />
      <Arrow x1={118} y1={ROW_Y.treps} x2={150} y2={ROW_Y.treps} label="" />
      <Arrow x1={118} y1={ROW_Y.market_repo} x2={150} y2={ROW_Y.market_repo} label="" />
      <Arrow x1={300} y1={ROW_Y.call} x2={500} y2={ROW_Y.call} label="settles bilaterally" dashed />
      <Arrow x1={300} y1={ROW_Y.treps} x2={330} y2={ROW_Y.treps} label="" />
      <Arrow x1={300} y1={ROW_Y.market_repo} x2={330} y2={ROW_Y.market_repo} label="" />
      <Arrow x1={454} y1={135} x2={500} y2={135} label="funds" />
      <Arrow x1={454} y1={200} x2={500} y2={200} label="G-secs" />
    </svg>
  );
}

/** CCIL: how call money trades on NDS-CALL and settles bank to bank, and how TREPS and market
 * repo clear through CCIL as central counterparty, with today's simulated rates and volumes. */
export function CcilPanel({ slot }: { slot: Slot }) {
  const data = slot.replies.CCIL?.data;
  if (!isCcilPanel(data)) return <Waiting what="the money market's plumbing (type CCIL)" />;
  const panel = data;
  const cite = (s: CcilSegment) => s.sources.map((k) => `[${String(k + 1)}]`).join('');
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2 overflow-auto">
      <Diagram panel={panel} />
      <table className="text-[10px]" aria-label="how each segment trades and settles">
        <thead>
          <tr className="text-term-muted">
            <th className="text-left font-normal">SEGMENT</th>
            <th className="px-1 text-left font-normal">DEALING</th>
            <th className="px-1 text-left font-normal">COLLATERAL</th>
            <th className="px-1 text-left font-normal">COUNTERPARTY</th>
            <th className="px-1 text-left font-normal">SETTLEMENT</th>
          </tr>
        </thead>
        <tbody>
          {panel.segments.map((s) => (
            <tr key={s.key} className="align-top">
              <td className="text-term-amber">
                {s.name}
                <span className="text-term-muted"> {cite(s)}</span>
              </td>
              <td className="px-1 text-term-text">
                {s.platform}: {s.dealing}
              </td>
              <td className="px-1 text-term-text">{s.collateral ?? 'none (unsecured)'}</td>
              <td className="px-1 text-term-text">{s.counterparty}</td>
              <td className="px-1 text-term-text">{s.settlement}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[10px] text-term-muted">
        Also on NDS-CALL: notice money {pct(panel.also_on_nds_call.notice.rate)}, term money{' '}
        {pct(panel.also_on_nds_call.term.rate)}. {panel.model}
      </p>
      <ol aria-label="sources" className="list-decimal pl-4 text-[10px] text-term-muted">
        {panel.sources.map((s) => (
          <li key={s.url}>
            {s.claim}{' '}
            <a href={s.url} target="_blank" rel="noreferrer" className="text-term-accent">
              {s.document}
            </a>
          </li>
        ))}
      </ol>
      <TeachNote code="CCIL" />
    </div>
  );
}
