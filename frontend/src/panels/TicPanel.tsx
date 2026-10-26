import { usdBn } from '../lib/format';
import { isTicPanel } from '../market/types';
import type { Slot } from '../store/market';
import { Stat, StatRow, TeachNote, Waiting } from './parts';

const SHOWN = 20;

/** TIC: the major foreign holders of Treasuries, live after any simulated sales, against the
 * Treasury's own TIC figures. */
export function TicPanel({ slot }: { slot: Slot }) {
  const data = slot.replies.TIC?.data;
  if (!isTicPanel(data)) return <Waiting what="the foreign holders (type TIC)" />;
  const holders = data.holders.slice(0, SHOWN);
  const top = holders[0]?.holdings ?? 1;
  const total = data.total ?? null;
  const sold = data.official_total !== null && total !== null ? data.official_total - total : 0;
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2">
      <StatRow>
        <Stat label="FOREIGN HOLDINGS">{usdBn(total)}</Stat>
        <Stat label={`TIC (${data.as_of.slice(0, 7)})`}>{usdBn(data.official_total)}</Stat>
        <Stat label="SOLD IN THE SIMULATION" tone={sold > 0.05 ? 'text-term-down' : undefined}>
          {usdBn(sold)}
        </Stat>
      </StatRow>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-[10px]" aria-label="foreign holders">
          <thead className="sticky top-0 bg-term-bg">
            <tr className="text-term-muted">
              <th className="w-6 text-right font-normal">#</th>
              <th className="px-1 text-left font-normal">HOLDER</th>
              <th className="px-1 text-right font-normal">NOW</th>
              <th className="px-1 text-right font-normal">TIC</th>
              <th className="px-1 text-right font-normal">CHANGE</th>
              <th className="px-1 text-right font-normal">SHARE</th>
              <th className="w-1/4 px-1 font-normal" />
            </tr>
          </thead>
          <tbody>
            {holders.map((h, i) => {
              const change = h.holdings - h.official;
              return (
                <tr key={h.country} className="whitespace-nowrap">
                  <td className="text-right text-term-muted">{String(i + 1)}</td>
                  <td className="px-1 text-term-text">
                    {h.country}
                    {h.selling && <span className="ml-1 text-term-down">SELLING</span>}
                  </td>
                  <td className="px-1 text-right">{usdBn(h.holdings)}</td>
                  <td className="px-1 text-right text-term-muted">{usdBn(h.official)}</td>
                  <td className={`px-1 text-right ${change < -0.05 ? 'text-term-down' : 'text-term-muted'}`}>
                    {Math.abs(change) < 0.05 ? '—' : usdBn(change)}
                  </td>
                  <td className="px-1 text-right">
                    {total ? `${((h.holdings / total) * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td className="px-1" aria-hidden="true">
                    <div className="h-1.5 bg-term-amber/70" style={{ width: `${String((h.holdings / top) * 100)}%` }} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-term-muted">
        <span className="text-term-amber">SHOCK JP 200B 10D</span> has a holder sell; the table follows it day
        by day. Holdings are TIC&apos;s, at market value, by the country where the securities are held in
        custody, which is not always the owner&apos;s.
      </p>
      <TeachNote code="TIC" />
    </div>
  );
}
