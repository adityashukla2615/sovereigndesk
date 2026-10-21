/** What the REPLAY chart draws: a pure function of its data and the play cursor. */

import type { TimeChartData } from '../components/TimeChart';
import type { Palette } from '../lib/palette';
import type { ReplayAnnotation, ReplayTarget } from '../market/types';

/** The day an annotation lands on: the first date on or after it where the actual path is
 * known (an announcement on a Sunday shows on Monday). */
export function annotationIndex(target: ReplayTarget, date: string): number {
  return target.dates.findIndex((d, i) => d >= date && target.actual[i] !== null);
}

/** What happened against the model's paths, revealed up to ``cursor`` (an index into the
 * dates). Annotations are numbered as in the timeline and appear as the replay reaches them. */
export function replayChart(
  target: ReplayTarget,
  cursor: number,
  annotations: ReplayAnnotation[],
  p: Palette,
): TimeChartData {
  const colours = [p.amber, p.accent, p.up];
  const upTo = (values: (number | null)[]) => values.map((v, i) => (i <= cursor ? v : null));
  const markers = annotations.flatMap((a, k) => {
    const i = annotationIndex(target, a.date);
    const date = target.dates[i];
    return i >= 0 && i <= cursor && date !== undefined ? [{ date, text: String(k + 1) }] : [];
  });
  return {
    dates: target.dates,
    lines: [
      { name: 'What happened', colour: p.text, values: upTo(target.actual) },
      ...target.models.map((m, k) => ({
        name: `Model: ${m.name}`,
        colour: colours[k % colours.length] ?? p.amber,
        dashed: k > 0,
        values: upTo(m.values),
      })),
    ],
    markers,
    digits: target.digits,
  };
}
