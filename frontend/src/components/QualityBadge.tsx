/** LIVE, or the STALE/SEED label of the inputs that are not fresh live data. */
export function QualityBadge({ labels, prefix }: { labels: readonly string[]; prefix?: string }) {
  const stale = labels.filter((label) => label !== 'LIVE');
  const text = stale.length === 0 ? 'LIVE' : (stale[0] ?? 'LIVE');
  const tone =
    stale.length === 0
      ? 'border-term-up text-term-up'
      : text.startsWith('SEED')
        ? 'border-term-amber text-term-amber'
        : 'border-term-down text-term-down';
  return (
    <span
      title={stale.length > 1 ? stale.join(', ') : undefined}
      className={`rounded-sm border px-1 text-[10px] leading-4 whitespace-nowrap ${tone}`}
    >
      {prefix ? `${prefix} ` : ''}
      {text}
      {stale.length > 1 ? ` +${String(stale.length - 1)}` : ''}
    </span>
  );
}
