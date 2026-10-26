import { describe, expect, it } from 'vitest';

import type { CommandReply } from '../market/types';
import type { Slot } from '../store/market';
import { PY_DATA, REPLAY_DATA, US_TICK } from '../test/marketData';
import { CORR_DATA, TAXCAL_DATA } from '../test/terminalData';
import { panelTable, tablesIn, toCsv } from './csv';

function slot(panel: string, data: unknown, extra: Record<string, unknown> = {}): Slot {
  const reply = (code: string, d: unknown): CommandReply => ({
    ok: true,
    code,
    message: '',
    panel,
    data: d as Record<string, unknown>,
  });
  const replies: Record<string, CommandReply> = { [panel]: reply(panel, data) };
  for (const [code, d] of Object.entries(extra)) replies[code] = reply(code, d);
  return { panel, command: panel, replies, message: '' };
}

describe('CSV export', () => {
  it('quotes what needs quoting and leaves blanks for missing values', () => {
    const csv = toCsv({ name: 't', columns: ['a', 'b'], rows: [['x, y', 'say "hi"'], [1.5, null], [Number.NaN, true]] });
    expect(csv).toBe('a,b\r\n"x, y","say ""hi"""\r\n1.5,\r\n,true\r\n');
  });

  it('finds arrays of records (nested fields dotted) and columns side by side', () => {
    const tables = tablesIn({
      rows: [{ a: 1, b: { c: 2 }, skip: [1, 2] }, { a: 3, d: 'x' }],
      x: [1, 2, 3],
      y: [4, 5, 6],
      lonely: [7, 8],
    });
    const byName = Object.fromEntries(tables.map((t) => [t.name, t]));
    expect(byName.rows).toEqual({ name: 'rows', columns: ['a', 'b.c', 'd'], rows: [[1, 2, null], [3, null, 'x']] });
    expect(byName['']).toEqual({ name: '', columns: ['x', 'y'], rows: [[1, 4], [2, 5], [3, 6]] });
  });

  it("takes each panel's own table", () => {
    const py = panelTable(slot('PY', PY_DATA), {});
    expect(py?.columns).toEqual(['shifts_bp', 'exact', 'duration_only', 'duration_convexity']);
    expect(py?.rows).toHaveLength(5);
    expect(panelTable(slot('TAXCAL', TAXCAL_DATA), {})?.name).toBe('projection');
    const replay = panelTable(slot('REPLAY', REPLAY_DATA), {});
    expect(replay?.columns).toEqual(['date', '30-year gilt: actual', '30-year gilt: forced selling × λ']);
    expect(replay?.rows[2]).toEqual(['2022-09-23', 4.1, 3.8]);
    const ust = panelTable(slot('UST', { official_close: { '10Y': 0.04 } }), { usCurve: US_TICK.curve });
    expect(ust?.rows.find((r) => r[0] === '10Y')).toEqual(['10Y', 0.041, 0.04]);
    const fed = panelTable(slot('FED', {}, { QT: { reserves: [3, 2.9], effr_iorb_spread: [0, 0.01] } }), {});
    expect(fed).toEqual({ name: 'qt', columns: ['reserves', 'effr_iorb_spread'], rows: [[3, 0], [2.9, 0.01]] });
    const corr = panelTable(slot('CORR', CORR_DATA), {}); // no table: its fields
    expect(corr?.columns).toEqual(['field', 'value']);
    expect(corr?.rows[0]).toEqual(['us.lower', 0.04]);
    expect(panelTable({ panel: 'CALL', command: 'CALL', replies: {}, message: '' }, {})).toBeNull();
  });
});
