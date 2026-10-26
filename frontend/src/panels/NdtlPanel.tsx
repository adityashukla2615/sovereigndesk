import { useMemo } from 'react';

import { croreCount, inrCr } from '../lib/format';
import { type BankRow, isNdtlPanel } from '../market/types';
import { type Slot, useMarket } from '../store/market';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

const KINDS: Record<string, string> = {
  PSB: 'public sector',
  PVT: 'private',
  FGN: 'foreign',
  SFB: 'small finance',
  PD: 'primary dealer',
};

function sum(rows: BankRow[], key: keyof BankRow): number {
  return rows.reduce((total, r) => total + (typeof r[key] === 'number' ? r[key] : 0), 0);
}

/** NDTL: the SYNTHETIC banks behind the call market. Each one's NDTL, the CRR it must hold with
 * RBI and where its balance stands, its SLR securities and MSF capacity, and today's call
 * positions against its limits. */
export function NdtlPanel({ slot }: { slot: Slot }) {
  const india = useMarket((s) => s.india);
  const data = slot.replies.NDTL?.data;
  const banks = useMemo(
    () => (isNdtlPanel(data) ? [...data.banks].sort((a, b) => b.ndtl - a.ndtl) : null),
    [data],
  );
  if (!banks) return <Waiting what="the bank universe (type NDTL)" />;
  const depositTakers = banks.filter((b) => b.kind !== 'PD');
  const crr = india?.crr ?? null;
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      <p className="border border-term-down px-2 py-0.5 text-[10px] text-term-down" role="note">
        SYNTHETIC: {String(banks.length)} generated banks, not real institutions. Their total NDTL is
        India&apos;s real NDTL (RBI&apos;s CRR requirement ÷ CRR); how it is split between them is
        generated.
      </p>
      <StatRow>
        <Stat label="NDTL">{inrCr(sum(depositTakers, 'ndtl'))}</Stat>
        <Stat label="CRR">
          {crr === null ? '—' : `${(crr * 100).toFixed(2)}%`}
          {india?.pending_crr
            ? ` → ${(india.pending_crr.crr * 100).toFixed(2)}% from ${india.pending_crr.from}`
            : ''}
        </Stat>
        <Stat label="TO HOLD WITH RBI">{inrCr(sum(depositTakers, 'requirement'))}</Stat>
        <Stat label="HELD NOW">{inrCr(sum(depositTakers, 'balance'))}</Stat>
        <Stat label="SLR SECURITIES">{inrCr(sum(depositTakers, 'slr_holdings'))}</Stat>
        <Stat label="MSF CAPACITY">{inrCr(sum(depositTakers, 'msf_capacity'))}</Stat>
        {india && (
          <Stat label="FORTNIGHT">
            {india.fortnight.start} → {india.fortnight.end}
          </Stat>
        )}
      </StatRow>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-[10px]" aria-label="synthetic banks">
          <thead className="sticky top-0 bg-term-bg">
            <tr className="text-term-muted">
              <th className="text-left font-normal">BANK</th>
              <th className="px-1 text-left font-normal">KIND</th>
              <th className="px-1 text-right font-normal">NDTL ₹ CR</th>
              <th className="px-1 text-right font-normal">CRR TO HOLD</th>
              <th className="px-1 text-right font-normal">BALANCE</th>
              <th className="px-1 text-right font-normal">TONIGHT&apos;S TARGET</th>
              <th className="px-1 text-right font-normal">SLR</th>
              <th className="px-1 text-right font-normal">MSF CAP</th>
              <th className="px-1 text-right font-normal">BORROWED</th>
              <th className="px-1 text-right font-normal">LENT</th>
              <th className="px-1 text-right font-normal">BORROW CAP (AVG / DAY)</th>
              <th className="px-1 text-right font-normal">FLOOR MISSES</th>
            </tr>
          </thead>
          <tbody>
            {banks.map((b) => {
              const dealer = b.kind === 'PD';
              const short = !dealer && b.balance < b.target - 1;
              return (
                <tr key={b.code} className="whitespace-nowrap">
                  <td className="text-term-text">{b.code}</td>
                  <td className="px-1 text-term-muted">{KINDS[b.kind] ?? b.kind}</td>
                  <td className="px-1 text-right">{dealer ? '—' : croreCount(b.ndtl)}</td>
                  <td className="px-1 text-right">{dealer ? '—' : croreCount(b.requirement)}</td>
                  <td className={`px-1 text-right ${short ? 'text-term-down' : ''}`}>
                    {dealer ? '—' : croreCount(b.balance)}
                  </td>
                  <td className="px-1 text-right">{dealer ? '—' : croreCount(b.target)}</td>
                  <td className="px-1 text-right">{croreCount(b.slr_holdings)}</td>
                  <td className="px-1 text-right">{dealer ? '—' : croreCount(b.msf_capacity)}</td>
                  <td className="px-1 text-right">{croreCount(b.borrowed)}</td>
                  <td className="px-1 text-right">{croreCount(b.lent)}</td>
                  <td className="px-1 text-right">
                    {croreCount(b.borrow_cap_avg)} / {croreCount(b.borrow_cap_peak)}
                  </td>
                  <td className={`px-1 text-right ${b.floor_breaches > 0 ? 'text-term-down' : ''}`}>
                    {String(b.floor_breaches)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-term-muted">
        <span className="text-term-amber">CRR 3.5</span> changes the ratio from the next fortnight and
        shows the liquidity it drains or releases.
      </p>
      <TeachNote code="NDTL" />
    </div>
  );
}
