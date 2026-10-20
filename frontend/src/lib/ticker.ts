import type { InTick, UsTick } from '../market/types';
import { bp, direction, pct, usdBn } from './format';

export interface Quote {
  label: string;
  text: string;
  move: -1 | 0 | 1;
  /** A STALE label when the quote rests on lagged data. */
  stale?: string | null;
}

/** The tape's quotes from the latest ticks; colours compare with the tick before. */
export function tickerQuotes(
  us: UsTick | null,
  usBefore: UsTick | null,
  india: InTick | null,
  indiaBefore: InTick | null,
): Quote[] {
  const quotes: Quote[] = [];
  if (us) {
    for (const tenor of ['2Y', '10Y', '30Y']) {
      const now = us.curve[tenor];
      quotes.push({ label: `UST ${tenor}`, text: pct(now, 3), move: direction(now, usBefore?.curve[tenor]) });
    }
    const slope = (t: UsTick | null) => {
      const ten = t?.curve['10Y'];
      const two = t?.curve['2Y'];
      return ten !== undefined && two !== undefined ? ten - two : null;
    };
    quotes.push({ label: '2s10s', text: bp(slope(us)), move: direction(slope(us), slope(usBefore)) });
    quotes.push({ label: 'EFFR', text: pct(us.effr, 3), move: direction(us.effr, usBefore?.effr) });
    quotes.push({ label: 'RESERVES', text: usdBn(us.reserves), move: direction(us.reserves, usBefore?.reserves) });
    quotes.push({ label: 'TP10', text: pct(us.term_premium), move: direction(us.term_premium, usBefore?.term_premium) });
    quotes.push({ label: 'DXY', text: us.dollar_index.toFixed(2), move: direction(us.dollar_index, usBefore?.dollar_index) });
  }
  if (india) {
    quotes.push({ label: 'WACR', text: pct(india.wacr), move: direction(india.wacr, indiaBefore?.wacr) });
    quotes.push({ label: 'REPO', text: pct(india.corridor.repo), move: direction(india.corridor.repo, indiaBefore?.corridor.repo) });
    quotes.push({
      label: 'SURPLUS',
      text: `${india.surplus_pct.toFixed(2)}% NDTL`,
      move: direction(india.surplus_pct, indiaBefore?.surplus_pct),
    });
    quotes.push({ label: 'TREPS', text: pct(india.segments.treps), move: direction(india.segments.treps, indiaBefore?.segments.treps) });
    quotes.push({
      label: 'TB 3M',
      text: pct(india.tbills['3M']),
      move: direction(india.tbills['3M'], indiaBefore?.tbills['3M']),
      stale: india.tbills_stale,
    });
    const ten = india.gsec?.points['10Y'];
    if (ten !== undefined) {
      quotes.push({
        label: 'IN 10Y',
        text: pct(ten, 3),
        move: direction(ten, indiaBefore?.gsec?.points['10Y']),
      });
    }
  }
  const spread = (i: InTick | null, u: UsTick | null) => {
    const a = i?.gsec?.points['10Y'];
    const b = u?.curve['10Y'];
    return a !== undefined && b !== undefined ? a - b : null;
  };
  const now = spread(india, us);
  if (now !== null) {
    quotes.push({ label: 'IN–US 10Y', text: bp(now), move: direction(now, spread(indiaBefore, usBefore)) });
  }
  return quotes;
}
