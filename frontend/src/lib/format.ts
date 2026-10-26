/** Number formats used across the terminal; they mirror backend/app/sim/events.py. */

/** A decimal rate as a percentage: 0.0525 → '5.25%'. */
export function pct(rate: number | null | undefined, digits = 2): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return '—';
  return `${(rate * 100).toFixed(digits)}%`;
}

/** A signed change in basis points: 0.0018 → '+18 bp'. */
export function bp(change: number | null | undefined, digits = 0): string {
  if (change === null || change === undefined || !Number.isFinite(change)) return '—';
  const value = change * 1e4;
  const shown = Math.abs(value) < 0.5 && digits === 0 ? value.toFixed(1) : value.toFixed(digits);
  return `${value >= 0 ? '+' : ''}${shown} bp`;
}

const crore = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });

/** Rupees in crore, switching to lakh crore at ₹1 lakh crore: 185873 → '₹1.86 lakh cr'. */
export function inrCr(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || !Number.isFinite(amount)) return '—';
  const sign = amount < 0 ? '−' : '';
  const size = Math.abs(amount);
  if (size >= 100_000) return `${sign}₹${(size / 100_000).toFixed(2)} lakh cr`;
  return `${sign}₹${crore.format(size)} cr`;
}

/** Crore for a table whose header carries the unit, in Indian grouping: 123456.7 → '1,23,457'. */
export function croreCount(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || !Number.isFinite(amount)) return '—';
  return `${amount < 0 ? '−' : ''}${crore.format(Math.abs(amount))}`;
}

/** US dollars in billions: 2980 → '$2.98tn', 95 → '$95bn'. */
export function usdBn(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || !Number.isFinite(amount)) return '—';
  const sign = amount < 0 ? '−' : '';
  const size = Math.abs(amount);
  if (size >= 1000) return `${sign}$${(size / 1000).toFixed(2)}tn`;
  return size >= 10 ? `${sign}$${size.toFixed(0)}bn` : `${sign}$${size.toFixed(1)}bn`;
}

/** Direction of a change for colouring: 1 up, -1 down, 0 unchanged or unknown. */
export function direction(now: number | null | undefined, before: number | null | undefined): -1 | 0 | 1 {
  if (now === null || now === undefined || before === null || before === undefined) return 0;
  const diff = now - before;
  if (Math.abs(diff) < 1e-12) return 0;
  return diff > 0 ? 1 : -1;
}
