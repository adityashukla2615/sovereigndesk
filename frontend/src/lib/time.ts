export const MARKET_ZONES = [
  { label: 'ET', timeZone: 'America/New_York' },
  { label: 'IST', timeZone: 'Asia/Kolkata' },
] as const;

const formatters = new Map<string, Intl.DateTimeFormat>();

/** `HH:MM:SS` (24-hour) wall-clock time in the given IANA zone. */
export function formatClock(date: Date, timeZone: string): string {
  let formatter = formatters.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-GB', {
      timeZone,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    });
    formatters.set(timeZone, formatter);
  }
  return formatter.format(date);
}
