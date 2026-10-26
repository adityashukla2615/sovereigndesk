/**
 * EXPORT CSV: a panel's main table, found in its replies' data. Each panel names the table it
 * is about (a path into its data); otherwise the largest table found is used, and failing
 * that, the reply's own fields as name/value pairs.
 */

import { DISPLAY_TENORS, GSEC_TENORS } from '../market/types';
import type { Slot } from '../store/market';

export type Cell = string | number | boolean | null;

export interface Table {
  name: string;
  columns: string[];
  rows: Cell[][];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isCell(value: unknown): value is Cell {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value);
}

/** One CSV field: quoted when it holds a comma, quote or line break (RFC 4180). */
function field(cell: Cell): string {
  if (cell === null) return '';
  const text = typeof cell === 'number' && !Number.isFinite(cell) ? '' : String(cell);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function toCsv(table: Table): string {
  const lines = [table.columns, ...table.rows].map((row) => row.map(field).join(','));
  return `${lines.join('\r\n')}\r\n`;
}

/** A record's scalar fields, nested objects as dotted names; arrays are left out. */
function flatten(record: Record<string, unknown>, prefix = '', out: Record<string, Cell> = {}) {
  for (const [key, value] of Object.entries(record)) {
    const name = prefix ? `${prefix}.${key}` : key;
    if (isCell(value)) out[name] = value;
    else if (isRecord(value)) flatten(value, name, out);
  }
  return out;
}

function fromRecords(name: string, records: Record<string, unknown>[]): Table | null {
  const flat = records.map((r) => flatten(r));
  const columns: string[] = [];
  for (const row of flat) for (const key of Object.keys(row)) if (!columns.includes(key)) columns.push(key);
  if (columns.length === 0) return null;
  return { name, columns, rows: flat.map((row) => columns.map((c) => row[c] ?? null)) };
}

/** Every table in a value: arrays of records, and equal-length arrays side by side. */
export function tablesIn(value: unknown, path = ''): Table[] {
  const tables: Table[] = [];
  if (Array.isArray(value)) {
    if (value.length > 0 && value.every(isRecord)) {
      const table = fromRecords(path, value);
      if (table) tables.push(table);
      value.forEach((item, i) => tables.push(...tablesIn(item, `${path}.${String(i)}`)));
    }
    return tables;
  }
  if (!isRecord(value)) return tables;
  const columns = Object.entries(value).filter(
    (entry): entry is [string, Cell[]] => Array.isArray(entry[1]) && entry[1].length > 1 && entry[1].every(isCell),
  );
  const length = columns[0]?.[1].length;
  const parallel = columns.filter(([, values]) => values.length === length);
  if (length !== undefined && parallel.length >= 2) {
    tables.push({
      name: path,
      columns: parallel.map(([key]) => key),
      rows: Array.from({ length }, (_, i) => parallel.map(([, values]) => values[i] ?? null)),
    });
  }
  for (const [key, child] of Object.entries(value)) {
    if (Array.isArray(child) || isRecord(child)) tables.push(...tablesIn(child, path ? `${path}.${key}` : key));
  }
  return tables;
}

function keyValues(name: string, data: Record<string, unknown>): Table | null {
  const rows = Object.entries(flatten(data)).map(([key, value]): Cell[] => [key, value]);
  return rows.length > 0 ? { name, columns: ['field', 'value'], rows } : null;
}

/** The table each panel is about, as a path into its own reply's data. */
const MAIN: Record<string, string> = {
  PY: '',
  WACR: 'real',
  SPRD: 'real',
  TAXCAL: 'projection',
  LINK: 'path',
  LAF: 'auctions',
  CALL: 'rounds',
  NDTL: 'banks',
  TIC: 'holders',
  CCIL: 'segments',
  DEBT: '',
  IMPACT: 'retail.holdings',
  MPC: 'backtest.recent',
  HELP: 'commands',
  GSEC: 'passthrough.estimates',
};

function curveTable(name: string, tenors: string[], series: Record<string, Record<string, number> | null>): Table {
  const names = Object.keys(series);
  return {
    name,
    columns: ['tenor', ...names],
    rows: tenors.map((t) => [t, ...names.map((n) => series[n]?.[t] ?? null)]),
  };
}

function replayTable(data: Record<string, unknown>): Table | null {
  const targets = data.targets;
  if (!Array.isArray(targets)) return null;
  const columns = ['date'];
  const byDate = new Map<string, Record<string, Cell>>();
  for (const target of targets) {
    if (!isRecord(target) || !Array.isArray(target.dates)) continue;
    const label = String(target.label);
    const series: [string, unknown][] = [[`${label}: actual`, target.actual]];
    if (Array.isArray(target.models)) {
      for (const m of target.models) if (isRecord(m)) series.push([`${label}: ${String(m.name)}`, m.values]);
    }
    for (const [column, values] of series) {
      if (!Array.isArray(values)) continue;
      columns.push(column);
      target.dates.forEach((date: unknown, i: number) => {
        const row = byDate.get(String(date)) ?? {};
        const v: unknown = values[i];
        row[column] = isCell(v) ? v : null;
        byDate.set(String(date), row);
      });
    }
  }
  const dates = [...byDate.keys()].sort();
  return { name: 'paths', columns, rows: dates.map((d) => [d, ...columns.slice(1).map((c) => byDate.get(d)?.[c] ?? null)]) };
}

/** The main table of a slot's panel, or null when it has no data yet. */
export function panelTable(slot: Slot, live: { usCurve?: Record<string, number> | null; gsec?: Record<string, number> | null }): Table | null {
  const data = slot.replies[slot.panel]?.data ?? Object.values(slot.replies).at(-1)?.data ?? null;
  if (slot.panel === 'UST' && (live.usCurve ?? data)) {
    const close = isRecord(data?.official_close) ? (data.official_close as Record<string, number>) : null;
    return curveTable('curve', DISPLAY_TENORS, { live: live.usCurve ?? null, official_close: close });
  }
  if (slot.panel === 'FED') {
    const qt = slot.replies.QT?.data;
    const projection = qt ? tablesIn(qt).find((t) => t.name === '') : undefined;
    if (projection) return { ...projection, name: 'qt' };
  }
  if (!data) return null;
  if (slot.panel === 'GSEC' && isRecord(data.close)) {
    return curveTable('curve', GSEC_TENORS, { fbil_close: data.close as Record<string, number>, live: live.gsec ?? null });
  }
  if (slot.panel === 'REPLAY') return replayTable(data);
  const tables = tablesIn(data);
  const preferred = MAIN[slot.panel];
  const chosen =
    tables.find((t) => preferred !== undefined && t.name === preferred) ??
    [...tables].sort((a, b) => b.rows.length * b.columns.length - a.rows.length * a.columns.length)[0];
  return chosen ?? keyValues('fields', data);
}
