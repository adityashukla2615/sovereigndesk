import { pct } from '../lib/format';
import { type CorridorMark, mergeMarks } from '../lib/corridor';

/**
 * A policy corridor drawn to scale across the panel: the band between floor and ceiling, the
 * administered rates in it, the market rate as a marker above and the model's target dashed.
 * Rates are decimals; marks at the same rate share one label.
 */
export function Corridor({
  floor,
  ceiling,
  marks,
  value,
  target,
  title,
}: {
  floor: CorridorMark;
  ceiling: CorridorMark;
  marks: CorridorMark[];
  value: CorridorMark;
  target?: CorridorMark | undefined;
  title: string;
}) {
  const pad = (ceiling.rate - floor.rate) * 0.35;
  const lo = Math.min(floor.rate, value.rate) - pad;
  const hi = Math.max(ceiling.rate, value.rate) + pad;
  const at = (rate: number) => `${String(((rate - lo) / (hi - lo)) * 100)}%`;
  const inside = value.rate >= floor.rate - 1e-12 && value.rate <= ceiling.rate + 1e-12;
  const tone = inside ? 'text-term-amber' : 'text-term-down';
  return (
    <div
      role="img"
      aria-label={`${title}: ${value.label} ${pct(value.rate)} between ${floor.label} ${pct(floor.rate)} and ${ceiling.label} ${pct(ceiling.rate)}`}
      className="relative h-[3.75rem] w-full shrink-0 select-none"
    >
      <div
        className={`absolute top-0 -translate-x-1/2 text-[11px] whitespace-nowrap ${tone}`}
        style={{ left: at(value.rate) }}
      >
        {value.label} {pct(value.rate, 3)}
      </div>
      <div
        aria-hidden="true"
        className={`absolute top-3.5 -translate-x-1/2 text-[10px] leading-none ${tone}`}
        style={{ left: at(value.rate) }}
      >
        ▼
      </div>
      <div
        className="absolute top-6 h-3 bg-term-line"
        style={{ left: at(floor.rate), width: `${String(((ceiling.rate - floor.rate) / (hi - lo)) * 100)}%` }}
      />
      {target && (
        <div
          title={`${target.label} ${pct(target.rate, 3)}`}
          className="absolute top-5 h-5 border-l border-dashed border-term-accent"
          style={{ left: at(target.rate) }}
        />
      )}
      {mergeMarks([floor, ...marks, ceiling]).map((m) => (
        <div
          key={m.label}
          className="absolute top-5 flex -translate-x-1/2 flex-col items-center"
          style={{ left: at(m.rate) }}
        >
          <div className="h-5 w-px bg-term-muted" />
          <div className="text-[10px] whitespace-nowrap text-term-muted">
            {m.label} {pct(m.rate)}
          </div>
        </div>
      ))}
    </div>
  );
}
