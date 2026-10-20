export interface CorridorMark {
  label: string;
  rate: number;
}

/** Marks at the same rate share one label (the Fed's ON RRP sits on the range's floor). */
export function mergeMarks(marks: readonly CorridorMark[]): CorridorMark[] {
  const merged: CorridorMark[] = [];
  for (const mark of marks) {
    const same = merged.find((m) => Math.abs(m.rate - mark.rate) < 1e-9);
    if (same) same.label = `${same.label} · ${mark.label}`;
    else merged.push({ ...mark });
  }
  return merged;
}

/** A simulated timestamp in a market's zone: '2026-10-20T05:12:00Z' → 'Tue 20 Oct 10:42'. */
export function simClock(iso: string, timeZone: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en-GB', {
    timeZone,
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
    .format(date)
    .replace(',', '');
}
