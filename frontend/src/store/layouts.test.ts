import { afterEach, describe, expect, it, vi } from 'vitest';

import type { CommandReply } from '../market/types';
import { deleteLayout, isSavedLayout, lastLayout, layoutOf, rememberLayout, saveLayout, savedLayouts } from './layouts';
import { initialSlots, routeReply } from './market';

const LAYOUT = { panels: ['PY', 'FED', 'WACR', 'CALL'], commands: ['PY 30Y', 'FED', 'WACR', 'CALL'], sizes: {} };

function answer(code: string, panel: string, command: string): CommandReply {
  return { ok: true, code, message: '', panel, data: null, command };
}

describe('layouts', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('saves, lists and deletes named layouts in this browser', () => {
    expect(savedLayouts()).toEqual({});
    expect(saveLayout('RATES', LAYOUT)).toBe(true);
    expect(savedLayouts()).toEqual({ RATES: LAYOUT });
    expect(deleteLayout('NOPE')).toBe(false);
    expect(deleteLayout('RATES')).toBe(true);
    expect(savedLayouts()).toEqual({});
  });

  it('ignores storage it cannot read or trust', () => {
    localStorage.setItem('sovereigndesk.layouts', '{"BAD": {"panels": ["PY"]}, "OK": ' + JSON.stringify(LAYOUT) + '}');
    expect(Object.keys(savedLayouts())).toEqual(['OK']);
    localStorage.setItem('sovereigndesk.layout.last', 'not json');
    expect(lastLayout()).toBeNull();
    expect(isSavedLayout({ ...LAYOUT, sizes: { columns: { left: 'wide' } } })).toBe(false);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(saveLayout('RATES', LAYOUT)).toBe(false); // a private window, say
  });

  it('remembers the last layout', () => {
    rememberLayout(LAYOUT);
    expect(lastLayout()).toEqual(LAYOUT);
  });

  it('keeps the command that fills each slot, not the actions run on it', () => {
    let slots = routeReply(initialSlots(), 0, answer('PY', 'PY', 'PY 30Y'));
    slots = routeReply(slots, 0, answer('QT', 'FED', 'QT 95B')); // an action on the FED panel
    slots = routeReply(slots, 3, answer('CALL', 'CALL', 'CALL'));
    expect(layoutOf(slots, {}).commands).toEqual(['PY 30Y', 'FED', 'WACR', 'CALL']);
  });
});
