import { describe, expect, it } from 'vitest';

import type { CommandReply } from '../market/types';
import { initialSlots, routeReply } from './market';

function reply(code: string, panel: string | null, ok = true): CommandReply {
  return { ok, code, message: `${code} done`, panel, data: { code } };
}

describe('routeReply', () => {
  it('refreshes the slot already showing the panel, keeping other replies for it', () => {
    const slots = routeReply(initialSlots(), 3, reply('FED', 'FED'));
    const after = routeReply(slots, 3, reply('QT', 'FED'));
    expect(after.map((s) => s.panel)).toEqual(['PY', 'FED', 'WACR', 'UST']);
    expect(Object.keys(after[1]?.replies ?? {})).toEqual(['FED', 'QT']);
    expect(after[1]?.message).toBe('QT done');
  });

  it('loads a new panel into the focused slot', () => {
    const after = routeReply(initialSlots(), 2, reply('CALL', 'CALL'));
    expect(after.map((s) => s.panel)).toEqual(['PY', 'FED', 'CALL', 'UST']);
    expect(Object.keys(after[2]?.replies ?? {})).toEqual(['CALL']);
  });

  it('lets an action refresh an open panel but never take a slot', () => {
    const slots = initialSlots();
    expect(routeReply(slots, 0, reply('VRR', 'LAF'))).toBe(slots); // no LAF panel open
    const after = routeReply(slots, 0, reply('HIKE', 'FED'));
    expect(after[1]?.replies.HIKE?.message).toBe('HIKE done');
    expect(after[0]?.panel).toBe('PY');
  });

  it('ignores failures, replies without a panel and teach toggles', () => {
    const slots = initialSlots();
    expect(routeReply(slots, 0, reply('PY', 'PY', false))).toBe(slots);
    expect(routeReply(slots, 0, reply('SPEED', null))).toBe(slots);
    expect(routeReply(slots, 0, reply('TEACH', 'TEACH'))).toBe(slots);
  });
});
