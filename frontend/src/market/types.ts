/**
 * Payloads of the simulator's WebSocket topics and of the command replies the panels render.
 * They mirror backend/app/sim/us_market.py (snapshot), backend/app/sim/india_market.py and
 * gsec.py (snapshot and panels), simulator.py (SPRD) and backend/app/commands/*.py: keep them
 * in step.
 */

import type { Nss } from '../lib/nss';

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
  /** `realistic`: WACR may leave the corridor as RBI's data shows; `policy`: clamped inside. */
  mode: 'realistic' | 'policy';
  /** Where call prints may go in the current mode. */
  band: { lower: number; upper: number };
  tbills_as_of: string;
  /** e.g. `STALE 8d` when FBIL's benchmarks are older than the threshold. */
  tbills_stale: string | null;
  /** The live G-sec curve, or null when FBIL's par yields could not be used. */
  gsec: GsecTick | null;
  /** The rupee and RBI's reserves, once a US shock has run through the linkage. */
  fx: { inr: number; reserves_bn: number | null; runs: number } | null;
  as_of: string;
}

/** The G-sec curve's tenors in years, in order (backend app.data.catalog.FBIL_GSEC_TENORS). */
export const GSEC_YEARS: Record<string, number> = {
  '3M': 0.25,
  '6M': 0.5,
  '1Y': 1,
  '2Y': 2,
  '3Y': 3,
  '5Y': 5,
  '7Y': 7,
  '10Y': 10,
  '14Y': 14,
  '20Y': 20,
  '30Y': 30,
};
export const GSEC_TENORS = Object.keys(GSEC_YEARS);

export interface GsecTick {
  /** Market points: the 91/182/364-day T-bills, then the coupon tenors at par. */
  points: Curve;
  /** The live NSS fit to the points. */
  nss: Nss;
  rmse_bp: number;
  /** Repo change since FBIL's publication (decimal). */
  repo_shift: number;
  as_of: string;
  stale: string | null;
}

export interface PassThroughEstimate {
  tenor: string;
  years: number;
  /** Response per unit of policy surprise (the 3-month move), with its bootstrap band. */
  relative: number;
  low: number;
  high: number;
  /** Same-day move per unit of the actual repo change. */
  day_beta: number;
}

export interface GsecPanelData {
  tenors: Record<string, number>;
  /** The curve on FBIL's day: T-bill benchmarks, then FBIL's par yields. */
  close: Curve;
  close_nss: Nss;
  close_rmse_bp: number;
  as_of: string;
  repo_at_close: number;
  passthrough: {
    kappa: number;
    gamma: number;
    scale: number;
    half_life_years: number;
    kappa_band: number[];
    gamma_band: number[];
    beta_10y_band: number[];
    rmse: number;
    level: number;
    events: { date: string; before: string; change: number; moves: Curve }[];
    estimates: PassThroughEstimate[];
    curve: { years: number; beta: number; expectations: number; tp: number }[];
  };
  factors: {
    level_sd: number;
    tp_sd: number;
    correlation: number;
    days: number;
    residual_bp: number;
    half_life_days: number;
  };
  now: GsecTick;
}

export interface SpreadPoint {
  date: string;
  india: number;
  us: number | null;
}

export interface SpreadPanelData {
  real: SpreadPoint[];
  simulated: SpreadPoint[];
  now: { india: number; us: number | null; spread: number | null };
  daily_from: string;
  india_as_of: string;
  us_as_of: string | null;
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
  mode: 'realistic' | 'policy';
  band: { lower: number; upper: number };
  excursions: {
    trading_days: number;
    below_sdf: number;
    above_msf: number;
    weekdays: number;
    weekday_below: number;
    weekday_above: number;
    simulated_below: number;
    simulated_above: number;
  };
}

export type MpcModelName = 'ordered logit' | 'xgboost' | 'taylor';

export interface MpcReport {
  accuracy: number;
  macro_f1: number;
  brier: number;
  /** Actual class (rows) against predicted class (columns). */
  confusion: number[][];
}

export interface MpcPanelData {
  classes: string[];
  as_of: string;
  next_meeting: string | null;
  /** Five class probabilities for the next decision, by model. */
  probabilities: Record<MpcModelName, number[]>;
  features: { key: string; label: string; now: number | null; last: number | null }[];
  taylor: {
    prescribed: number;
    repo: number;
    inflation: number;
    output_gap: number | null;
    r_star: number;
    pi_star: number;
  };
  backtest: {
    first: string;
    forecasts: number;
    models: Record<string, MpcReport>;
    recent: {
      date: string;
      scheduled: boolean;
      change_bp: number;
      actual: number;
      predicted: Record<string, number>;
      p_actual: Record<string, number>;
    }[];
  };
  sample: { first: string; last: string; decisions: number; counts: number[]; off_cycle: number };
  core_weights: { base: string; excluded: Record<string, number>; rmse: number; months: number }[];
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

export function isGsecPanel(value: unknown): value is GsecPanelData {
  return (
    isRecord(value) &&
    isRecord(value.close) &&
    isRecord(value.passthrough) &&
    Array.isArray(value.passthrough.estimates)
  );
}

export interface ImpactHolding {
  name: string;
  kind: 'bond' | 'fund';
  years: number | null;
  coupon: number | null;
  face: number | null;
  base_yield: number | null;
  spread_bp: number | null;
  dy_bp: number;
  value0: number;
  value1: number;
  change: number;
  exact_pct: number | null;
  duration_pct: number;
  convexity_pct: number;
  modified_duration: number;
  convexity: number;
  dv01: number;
  hold: {
    coupons: number;
    redemption: number;
    payments: number;
    bought_yield: number;
    realised_yield: number;
    sale_proceeds: number;
    sale_gain: number;
  } | null;
}

export interface ImpactLoan {
  amount: number;
  benchmark: 'EBLR' | 'MCLR';
  spread: number;
  reset_months: number;
  first_reset_month: number;
  tenor_months: number;
}

export interface ImpactProfile {
  monthly_sales: number;
  cost_share: number;
  import_share: number;
  fx_to_price: number;
  inventory_days: number;
  rate_semi_elasticity: number;
  price_elasticity: number;
  loan: ImpactLoan;
}

export interface ImpactBusiness {
  key: string;
  name: string;
  profile: ImpactProfile;
  base_rate: number;
  base_interest: number;
  base_margin: number;
  months: number[];
  loan_rate_bp: number[];
  interest: number[];
  import_cost: number[];
  price_pct: number[];
  volume_pct: number[];
  sales: number[];
  margin: number[];
  summary: {
    loan_rate_bp: number;
    interest: number;
    margin: number;
    margin_pct: number | null;
    sales_pct: number;
    year_margin: number;
  };
}

/** IMPACT: Module E's two views (backend app.sim.impact.impact_panel). */
export interface ImpactPanelData {
  illustrative: boolean;
  view?: 'RETAIL' | 'BUSINESS';
  profile?: string | null;
  shock: {
    source: 'simulation' | 'hypothetical';
    notes: string[];
    as_of: string | null;
    curve: { tenor: string; years: number; base: number; now: number; change_bp: number }[];
    repo_bp: number;
    money_bp: number;
    liquidity_bp: number;
    inr_pct: number;
    inr_base: number | null;
    inr_now: number | null;
  };
  retail: {
    holdings: ImpactHolding[];
    totals: {
      value0: number;
      value1: number;
      change: number;
      change_pct: number;
      duration_only: number;
      duration_convexity: number;
      modified_duration: number;
      convexity: number;
      dv01: number;
    } | null;
  };
  business: ImpactBusiness[];
  passthrough: {
    eblr_per_repo: number;
    eblr_lag_months: number;
    mclr_per_repo: number;
    mclr_months: number;
    mclr_per_money: number;
    mclr_fit: { share: number; months: number; rmse_bp: number; n: number; sample: string };
    mclr_now: number;
    mclr_as_of: string;
    repo_base: number;
  };
}

export function isImpactPanel(value: unknown): value is ImpactPanelData {
  return isRecord(value) && isRecord(value.shock) && isRecord(value.retail) && Array.isArray(value.business);
}

export interface ReplayScore {
  n: number;
  rmse: number;
  mae: number;
  direction: number | null;
  peak_model: number;
  peak_actual: number;
  peak_lag: number;
  end_model: number;
  end_actual: number;
}

export interface ReplayTarget {
  key: string;
  label: string;
  unit: string;
  digits: number;
  dates: string[];
  actual: (number | null)[];
  models: { name: string; values: (number | null)[] }[];
  scores: Record<string, ReplayScore>;
  summary: string[];
}

export interface ReplayAnnotation {
  date: string;
  text: string;
  source: string;
}

/** REPLAY: a real episode, the model against what happened (backend app.sim.replay.replay_panel). */
export interface ReplayPanelData {
  episode: {
    id: string;
    title: string;
    summary: string;
    start: string;
    end: string;
    segments: { start: string; end: string; peak_bp: number }[];
    sources: Record<string, string | null>;
  };
  annotations: ReplayAnnotation[];
  targets: ReplayTarget[];
  facts: Record<string, unknown>;
  notes: string[];
  available: { id: string; title: string }[];
}

export function isReplayPanel(value: unknown): value is ReplayPanelData {
  return isRecord(value) && isRecord(value.episode) && Array.isArray(value.targets) && Array.isArray(value.annotations);
}

export type LinkResponse = 'none' | 'vrr' | 'omo' | 'swap' | 'hike';

export interface LinkNode {
  key: string;
  label: string;
  value: number;
  unit: string;
  detail: string;
}

export interface LinkEstimate {
  key: string;
  label: string;
  value: number | null;
  low: number | null;
  high: number | null;
  used: number;
  n: number;
  r2: number | null;
  sample: string;
  method: string;
}

/** LINK: a US shock through India's markets (backend app.sim.linkage.link_panel). */
export interface LinkPanelData {
  mode: 'preview' | 'run';
  response: LinkResponse;
  responses: LinkResponse[];
  response_labels: Record<string, string>;
  nodes: LinkNode[];
  progress: { day: number; days: number; dates: string[] | null };
  path: {
    fpi_bn: number[];
    rbi_bn: number[];
    inr: number[];
    reserves_bn: number[];
    surplus_pct: number[];
    wacr_bp: number[];
    vrr_cr: number[];
  };
  live: {
    inr: number;
    reserves_bn: number;
    surplus_pct: number;
    wacr: number;
    repo: number;
    runs: number;
  };
  anchors: { inr: number; inr_as_of: string; reserves_bn: number; reserves_as_of: string };
  estimates: LinkEstimate[];
  assumptions: Record<string, number>;
}

export function isLinkPanel(value: unknown): value is LinkPanelData {
  return isRecord(value) && Array.isArray(value.nodes) && isRecord(value.path) && isRecord(value.live);
}

export function isMpcPanel(value: unknown): value is MpcPanelData {
  return (
    isRecord(value) &&
    Array.isArray(value.classes) &&
    isRecord(value.probabilities) &&
    isRecord(value.backtest)
  );
}

export function isSpreadPanel(value: unknown): value is SpreadPanelData {
  return isRecord(value) && Array.isArray(value.real) && isRecord(value.now) && 'daily_from' in value;
}

export function curveOf(value: unknown, key: string): Curve | null {
  if (!isRecord(value)) return null;
  const curve = value[key];
  return isRecord(curve) ? (curve as Curve) : null;
}
