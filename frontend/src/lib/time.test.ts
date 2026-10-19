import { describe, expect, it } from 'vitest';

import { formatClock } from './time';

describe('formatClock', () => {
  it('renders New York and Mumbai wall-clock time, DST included', () => {
    const winter = new Date('2026-01-15T15:30:05Z'); // EST = UTC-5
    const summer = new Date('2026-07-15T15:30:05Z'); // EDT = UTC-4
    expect(formatClock(winter, 'America/New_York')).toBe('10:30:05');
    expect(formatClock(summer, 'America/New_York')).toBe('11:30:05');
    expect(formatClock(winter, 'Asia/Kolkata')).toBe('21:00:05'); // IST = UTC+5:30, no DST
  });

  it('uses a 24-hour clock', () => {
    expect(formatClock(new Date('2026-03-02T00:05:00Z'), 'UTC')).toBe('00:05:00');
  });
});
