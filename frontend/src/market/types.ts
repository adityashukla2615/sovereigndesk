/**
 * Payloads of the simulator's WebSocket topics and of the command replies the panels render.
 * They mirror backend/app/sim/us_market.py (snapshot), backend/app/sim/india_market.py
 * (snapshot and panels) and backend/app/commands/*.py: keep them in step.
 */

export type Curve = Record<string, number>;

/** The par-curve tenors the simulator publishes (backend us_market.DISPLAY_TENORS). */
export const DISPLAY_TENORS = ['1M', '3M', '6M', '1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '20Y', '30Y'];

export interface UsTick {
  sim_time: string;
  curve: Curve;
  effr: number;
  effr_target: number;
  corridor: { lower: number; upper: number; iorb: number; on_rrp: number; srf: number };
  reserves: number;
  on_rrp_balance: number;
  reserves_ratio: number;
  fed_assets: number;
  qt: { treasury_cap: number; mbs_cap: number; halted: boolean };
  term_premium: number;
  dollar_index: number;
  selling: { country: string; total: number; sold: number; days: number }[];
  as_of: string;
}

export interface InTick {
  sim_time: string;
  time: string;
  session_open: boolean;
  corridor: { sdf: number; repo: number; msf: number };
  wacr: number;
  wacr_today: number | null;
  last_print: number | null;
  map_rate: number;
  call: { volume: number; high: number | null; low: number | null; rounds: number };
  surplus: number;
  surplus_pct: number;
  ndtl: number;
  laf: { sdf: number; msf: number; vrr: number; vrrr: number };
  segments: { treps: number; market_repo: number; notice: number; term: number };
  tbills: Record<string, number>;
  crr: number;
  pending_crr: { from: string; crr: number } | null;
  fortnight: { start: string; end: string };
  rejected_today: number;
  as_of: string;
}

export interface PriceYieldData {
  tenor: string;
  ytm: number;
  price: number;
  macaulay: number;
  modified: number;
  convexity: number;
  dv01: number;
  shifts_bp: number[];
  exact: number[];
  duration_only: number[];
  duration_convexity: number[];
}

export interface ReserveCurve {
  abundant: number;
  scarce: number;
  midpoint: number;
  width: number;
  fit_rmse_bp: number;
}

export interface QtProjection {
  monthly_total: number;
  reserves: number[];
  effr_iorb_spread: number[];
  ten_year_term_premium_change: number[];
}

export interface CorridorPanelData {
  map: {
    deficit: number;
    surplus: number;
    midpoint: number;
    width: number;
    rmse_bp: number;
    points: number;
  };
  curve: { surplus_pct: number; rate: number }[];
  now: { surplus_pct: number; map_rate: number; wacr: number };
  real: { date: string; spread: number }[];
  simulated: { date: string; spread: number }[];
}

export interface CommandReply {
  ok: boolean;
  code: string;
  message: string;
  panel: string | null;
  data: Record<string, unknown> | null;
  narrated?: boolean;
  sim_time?: string | null;
}

export interface CommandInfo {
  code: string;
  usage: string;
  summary: string;
  group: string;
  available: boolean;
  available_in: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isCommandReply(value: unknown): value is CommandReply {
  return (
    isRecord(value) &&
    typeof value.ok === 'boolean' &&
    typeof value.code === 'string' &&
    typeof value.message === 'string'
  );
}

export function isUsTick(value: unknown): value is UsTick {
  return isRecord(value) && isRecord(value.curve) && typeof value.effr === 'number';
}

export function isInTick(value: unknown): value is InTick {
  return isRecord(value) && isRecord(value.corridor) && typeof value.wacr === 'number';
}

function isNumberArray(value: unknown): value is number[] {
  return Array.isArray(value) && value.every((v) => typeof v === 'number');
}

export function isPriceYield(value: unknown): value is PriceYieldData {
  return (
    isRecord(value) &&
    typeof value.tenor === 'string' &&
    isNumberArray(value.shifts_bp) &&
    isNumberArray(value.exact)
  );
}

export function isQtProjection(value: unknown): value is QtProjection {
  return isRecord(value) && isNumberArray(value.reserves) && isNumberArray(value.effr_iorb_spread);
}

export function reserveCurveOf(value: unknown): ReserveCurve | null {
  if (!isRecord(value) || !isRecord(value.reserve_curve)) return null;
  const c = value.reserve_curve;
  return typeof c.midpoint === 'number' && typeof c.width === 'number'
    ? (c as unknown as ReserveCurve)
    : null;
}

export function isCorridorPanel(value: unknown): value is CorridorPanelData {
  return isRecord(value) && isRecord(value.map) && Array.isArray(value.real);
}

export function curveOf(value: unknown, key: string): Curve | null {
  if (!isRecord(value)) return null;
  const curve = value[key];
  return isRecord(curve) ? (curve as Curve) : null;
}
