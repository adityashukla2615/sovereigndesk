import { useMemo, useState } from 'react';

import { type ImpactRequest, apiPost } from '../api/client';
import { LazyChart as Chart } from '../components/LazyChart';
import { pct } from '../lib/format';
import { palette } from '../lib/palette';
import {
  type ImpactBusiness,
  type ImpactLoan,
  type ImpactPanelData,
  type ImpactProfile,
  isImpactPanel,
} from '../market/types';
import type { Slot } from '../store/market';
import { businessOption } from './impactOptions';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

type Tab = 'RETAIL' | 'BUSINESS';

interface BondRow {
  kind: 'bond';
  name: string;
  face: number;
  coupon: number;
  years: number;
  spread_bp: number;
}

interface FundRow {
  kind: 'fund';
  name: string;
  value: number;
  modified_duration: number;
  convexity: number;
}

type Row = BondRow | FundRow;

interface Hypothetical {
  shift_bp: string;
  repo_bp: string;
  inr_pct: string;
}

const NO_MOVE: Hypothetical = { shift_bp: '', repo_bp: '', inr_pct: '' };

function rowsOf(panel: ImpactPanelData): Row[] {
  return panel.retail.holdings.map((h) =>
    h.kind === 'bond'
      ? {
          kind: 'bond',
          name: h.name,
          face: h.face ?? h.value0,
          coupon: h.coupon ?? 0,
          years: h.years ?? 1,
          spread_bp: Math.round(h.spread_bp ?? 0),
        }
      : { kind: 'fund', name: h.name, value: h.value0, modified_duration: h.modified_duration, convexity: h.convexity },
  );
}

function signed(v: number | null | undefined, digits = 2, unit = ''): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}${unit}`;
}

/** Signed rupees in the Indian grouping: −12345.6 → '−₹12,346'. */
function rupees(v: number): string {
  if (!Number.isFinite(v)) return '—';
  const sign = v < 0 ? '−' : v > 0 ? '+' : '';
  return `${sign}₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

function NumberCell({
  value,
  onChange,
  label,
  step = 'any',
  wide = false,
}: {
  value: number;
  onChange: (v: number) => void;
  label: string;
  step?: string;
  wide?: boolean;
}) {
  return (
    <input
      type="number"
      aria-label={label}
      value={Number.isFinite(value) ? value : ''}
      step={step}
      onChange={(e) => {
        onChange(Number(e.target.value));
      }}
      className={`${wide ? 'w-24' : 'w-14'} rounded-sm border border-term-line bg-term-panel px-0.5 text-right text-[11px] text-term-text`}
    />
  );
}

function MoveInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex items-center gap-1 text-[10px] text-term-muted">
      {label}
      <input
        type="number"
        aria-label={label}
        value={value}
        placeholder="sim"
        onChange={(e) => {
          onChange(e.target.value);
        }}
        className="w-14 rounded-sm border border-term-line bg-term-panel px-0.5 text-right text-[11px] text-term-text"
      />
    </label>
  );
}

function toNumber(text: string): number | null {
  if (text.trim() === '') return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

function Retail({
  panel,
  rows,
  setRows,
}: {
  panel: ImpactPanelData;
  rows: Row[];
  setRows: (rows: Row[]) => void;
}) {
  const t = panel.retail.totals;
  const update = (i: number, change: Partial<BondRow> | Partial<FundRow>) => {
    setRows(rows.map((r, k) => (k === i ? ({ ...r, ...change } as Row) : r)));
  };
  return (
    <div className="flex min-h-0 flex-col gap-1 overflow-auto">
      <table className="text-[11px]" aria-label="portfolio">
        <thead>
          <tr className="text-term-muted">
            <th className="text-left font-normal">HOLDING (ILLUSTRATIVE)</th>
            <th className="px-1 font-normal">SIZE ₹</th>
            <th className="px-1 font-normal">CPN %</th>
            <th className="px-1 font-normal">YRS / D</th>
            <th className="px-1 font-normal">Δy</th>
            <th className="px-1 font-normal">EXACT</th>
            <th className="px-1 font-normal">DUR</th>
            <th className="px-1 font-normal">D+C</th>
            <th className="px-1 font-normal">ΔVALUE</th>
            <th className="px-1 font-normal">HOLD / SELL</th>
          </tr>
        </thead>
        <tbody>
          {panel.retail.holdings.map((h, i) => {
            const row = rows[i];
            return (
              <tr key={`${h.name}-${String(i)}`}>
                <td className="truncate text-term-text">{h.name}</td>
                <td className="px-1 text-right">
                  {row?.kind === 'bond' ? (
                    <NumberCell label={`${h.name} face`} value={row.face} onChange={(v) => { update(i, { face: v }); }} wide />
                  ) : row?.kind === 'fund' ? (
                    <NumberCell label={`${h.name} value`} value={row.value} onChange={(v) => { update(i, { value: v }); }} wide />
                  ) : null}
                </td>
                <td className="px-1 text-right">
                  {row?.kind === 'bond' ? (
                    <NumberCell
                      label={`${h.name} coupon`}
                      value={Math.round(row.coupon * 1e4) / 100}
                      onChange={(v) => { update(i, { coupon: v / 100 }); }}
                    />
                  ) : (
                    <span className="text-term-muted">fund</span>
                  )}
                </td>
                <td className="px-1 text-right">
                  {row?.kind === 'bond' ? (
                    <NumberCell label={`${h.name} years`} value={row.years} onChange={(v) => { update(i, { years: v }); }} />
                  ) : row?.kind === 'fund' ? (
                    <NumberCell
                      label={`${h.name} duration`}
                      value={row.modified_duration}
                      onChange={(v) => { update(i, { modified_duration: v }); }}
                    />
                  ) : null}
                </td>
                <td className="px-1 text-right text-term-muted">{signed(h.dy_bp, 1)}</td>
                <td className="px-1 text-right text-term-text">{signed(h.exact_pct, 2, '%')}</td>
                <td className="px-1 text-right text-term-muted">{signed(h.duration_pct, 2, '%')}</td>
                <td className="px-1 text-right text-term-muted">{signed(h.convexity_pct, 2, '%')}</td>
                <td className={`whitespace-nowrap px-1 text-right ${h.change < 0 ? 'text-term-down' : 'text-term-up'}`}>
                  {rupees(h.change)}
                </td>
                <td
                  className="whitespace-nowrap px-1 text-right text-[10px] text-term-muted"
                  title="Held to maturity: the realised yield with coupons reinvested at the new yield; sold now: the gain or loss crystallised"
                >
                  {h.hold
                    ? `${pct(h.hold.realised_yield)} held / ${rupees(h.hold.sale_gain)} sold`
                    : 'no cash flows'}
                </td>
              </tr>
            );
          })}
          {t && (
            <tr className="whitespace-nowrap border-t border-term-line text-term-amber">
              <td>TOTAL</td>
              <td className="px-1 text-right">₹{Math.round(t.value0).toLocaleString('en-IN')}</td>
              <td />
              <td className="px-1 text-right">D {t.modified_duration.toFixed(2)}</td>
              <td />
              <td className="px-1 text-right">{signed(t.change_pct, 2, '%')}</td>
              <td className="px-1 text-right">{rupees(t.duration_only)}</td>
              <td className="px-1 text-right">{rupees(t.duration_convexity)}</td>
              <td className="px-1 text-right">{rupees(t.change)}</td>
              <td className="px-1 text-right text-[10px]">DV01 ₹{Math.round(t.dv01).toLocaleString('en-IN')}/bp</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** The profile's editable parameters (ILLUSTRATIVE presets). */
function ProfileEditor({ profile, onChange }: { profile: ImpactProfile; onChange: (p: ImpactProfile) => void }) {
  const loan = profile.loan;
  const setLoan = (change: Partial<ImpactLoan>) => {
    onChange({ ...profile, loan: { ...loan, ...change } });
  };
  const field = (label: string, value: number, set: (v: number) => void, wide = false) => (
    <label key={label} className="flex items-center justify-between gap-1 text-[10px] text-term-muted">
      {label}
      <NumberCell label={label} value={value} onChange={set} wide={wide} />
    </label>
  );
  return (
    <div className="grid grid-cols-3 gap-x-3 gap-y-0.5" aria-label="business profile">
      {field('LOAN ₹', loan.amount, (v) => { setLoan({ amount: v }); }, true)}
      <label className="flex items-center justify-between gap-1 text-[10px] text-term-muted">
        BENCHMARK
        <select
          aria-label="BENCHMARK"
          value={loan.benchmark}
          onChange={(e) => { setLoan({ benchmark: e.target.value === 'MCLR' ? 'MCLR' : 'EBLR' }); }}
          className="rounded-sm border border-term-line bg-term-panel text-[11px] text-term-text"
        >
          <option value="EBLR">EBLR</option>
          <option value="MCLR">MCLR</option>
        </select>
      </label>
      {field('SPREAD %', Math.round(loan.spread * 1e4) / 100, (v) => { setLoan({ spread: v / 100 }); })}
      {field('RESET (MONTHS)', loan.reset_months, (v) => { setLoan({ reset_months: Math.max(1, Math.round(v)) }); })}
      {field('FIRST RESET (MONTHS)', loan.first_reset_month, (v) => { setLoan({ first_reset_month: Math.max(0, Math.round(v)) }); })}
      {field('TENOR (MONTHS)', loan.tenor_months, (v) => { setLoan({ tenor_months: Math.max(1, Math.round(v)) }); })}
      {field('SALES ₹/MONTH', profile.monthly_sales, (v) => { onChange({ ...profile, monthly_sales: v }); }, true)}
      {field('IMPORTED %', Math.round(profile.import_share * 1000) / 10, (v) => { onChange({ ...profile, import_share: v / 100 }); })}
      {field('INVENTORY DAYS', profile.inventory_days, (v) => { onChange({ ...profile, inventory_days: v }); })}
    </div>
  );
}

function Business({
  business,
  profile,
  onChange,
}: {
  business: ImpactBusiness;
  profile: ImpactProfile;
  onChange: (p: ImpactProfile) => void;
}) {
  const option = useMemo(() => businessOption(business, palette()), [business]);
  const s = business.summary;
  const loan = business.profile.loan;
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-auto">
      <StatRow>
        <Stat label={`${loan.benchmark} LOAN, ${String(loan.reset_months)}M RESET`}>
          {pct(business.base_rate)} {signed(s.loan_rate_bp, 0, ' bp')}
        </Stat>
        <Stat label="INTEREST / MONTH">{rupees(s.interest)}</Stat>
        <Stat label="MARGIN / MONTH" tone={s.margin < 0 ? 'text-term-down' : 'text-term-up'}>
          {rupees(s.margin)} ({signed(s.margin_pct, 1, '%')})
        </Stat>
        <Stat label="SALES">{signed(s.sales_pct, 2, '%')}</Stat>
        <Stat label={`MARGIN, ${String(business.months.length)} MONTHS`}>{rupees(s.year_margin)}</Stat>
      </StatRow>
      <ProfileEditor profile={profile} onChange={onChange} />
      <div className="min-h-28 flex-1">
        <Chart option={option} label={`${business.name}: interest, imported costs and margin by month`} />
      </div>
    </div>
  );
}

const replyIds = new WeakMap<object, number>();
let nextReplyId = 0;

/** A stable key per reply object, so a new reply (a new IMPACT command) resets the editors. */
function replyKey(reply: object): string {
  let id = replyIds.get(reply);
  if (id === undefined) {
    id = nextReplyId++;
    replyIds.set(reply, id);
  }
  return String(id);
}

/** IMPACT: the simulated (or a hypothetical) shock for a bond portfolio and small businesses. */
export function ImpactPanel({ slot }: { slot: Slot }) {
  const reply = slot.replies.IMPACT?.data;
  if (!isImpactPanel(reply)) {
    return <Waiting what="the impact views (type IMPACT, IMPACT RETAIL +100BP or IMPACT BUSINESS IMPORTER)" />;
  }
  return <ImpactView key={replyKey(reply)} initial={reply} />;
}

function ImpactView({ initial }: { initial: ImpactPanelData }) {
  const [edited, setEdited] = useState<ImpactPanelData | null>(null);
  const [tab, setTab] = useState<Tab>(initial.view ?? 'RETAIL');
  const [profileKey, setProfileKey] = useState<string | null>(initial.profile ?? null);
  const [rows, setRows] = useState<Row[]>(() => rowsOf(initial));
  const [move, setMove] = useState<Hypothetical>(NO_MOVE);
  const [profiles, setProfiles] = useState<Record<string, ImpactProfile>>(() =>
    Object.fromEntries(initial.business.map((b) => [b.key, b.profile])),
  );
  const [error, setError] = useState<string | null>(null);
  const panel = edited ?? initial;
  const business = panel.business.find((b) => b.key === profileKey) ?? panel.business[0];
  const apply = async () => {
    const body: ImpactRequest = {
      bonds: rows
        .filter((r): r is BondRow => r.kind === 'bond')
        .map((b) => ({ name: b.name, face: b.face, coupon: b.coupon, years: b.years, spread_bp: b.spread_bp })),
      funds: rows
        .filter((r): r is FundRow => r.kind === 'fund')
        .map((f) => ({ name: f.name, value: f.value, modified_duration: f.modified_duration, convexity: f.convexity })),
      profiles: panel.business.map((b) => ({ key: b.key, name: b.name, ...(profiles[b.key] ?? b.profile) })),
      shift_bp: toNumber(move.shift_bp),
      repo_bp: toNumber(move.repo_bp),
      inr_pct: toNumber(move.inr_pct),
    };
    try {
      const next = await apiPost('/api/impact', body);
      if (isImpactPanel(next)) {
        setEdited(next);
        setError(null);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };
  const s = panel.shock;
  const ten = s.curve.find((c) => c.tenor === '10Y');
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      <StatRow>
        <Stat label="SHOCK" tone="text-term-amber">
          {s.source === 'simulation' ? 'SIMULATION' : 'HYPOTHETICAL'}
        </Stat>
        <Stat label="REPO">{signed(s.repo_bp, 0, ' bp')}</Stat>
        <Stat label="10Y G-SEC">{signed(ten?.change_bp, 1, ' bp')}</Stat>
        <Stat label="RUPEE">{signed(s.inr_pct, 2, '%')}</Stat>
        <Stat label="MCLR (1Y MEDIAN)">
          {pct(panel.passthrough.mclr_now)} · {(panel.passthrough.mclr_per_repo * 100).toFixed(0)}% of repo in{' '}
          {panel.passthrough.mclr_months.toFixed(1)}m
        </Stat>
      </StatRow>
      <div className="flex flex-wrap items-center gap-1 text-[10px]" role="group" aria-label="impact view">
        {(['RETAIL', 'BUSINESS'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => {
              setTab(t);
            }}
            className={`rounded-sm border px-1 ${t === tab ? 'border-term-amber text-term-amber' : 'border-term-line text-term-text hover:border-term-amber'}`}
          >
            {t}
          </button>
        ))}
        {tab === 'BUSINESS' &&
          panel.business.map((b) => (
            <button
              key={b.key}
              type="button"
              title={b.name}
              onClick={() => {
                setProfileKey(b.key);
              }}
              className={`rounded-sm border px-1 ${b.key === business?.key ? 'border-term-accent text-term-accent' : 'border-term-line text-term-muted hover:border-term-accent'}`}
            >
              {b.key}
            </button>
          ))}
        <span className="ml-auto flex items-center gap-2">
          {tab === 'RETAIL' ? (
            <MoveInput label="YIELDS ±BP" value={move.shift_bp} onChange={(v) => { setMove({ ...move, shift_bp: v }); }} />
          ) : (
            <>
              <MoveInput label="REPO ±BP" value={move.repo_bp} onChange={(v) => { setMove({ ...move, repo_bp: v }); }} />
              <MoveInput label="RUPEE ±%" value={move.inr_pct} onChange={(v) => { setMove({ ...move, inr_pct: v }); }} />
            </>
          )}
          <button
            type="button"
            onClick={() => void apply()}
            className="rounded-sm border border-term-amber px-1 text-term-amber hover:bg-term-amber/20"
          >
            APPLY
          </button>
        </span>
      </div>
      {error && <p className="text-[10px] text-term-down">{error}</p>}
      {tab === 'RETAIL' ? (
        <Retail panel={panel} rows={rows} setRows={setRows} />
      ) : business ? (
        <Business
          business={business}
          profile={profiles[business.key] ?? business.profile}
          onChange={(p) => {
            setProfiles({ ...profiles, [business.key]: p });
          }}
        />
      ) : null}
      <TeachNote code="IMPACT" />
    </div>
  );
}
