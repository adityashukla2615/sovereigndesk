/** Tick and panel payloads shaped like the backend's, for component tests. */

import type {
  CorridorPanelData,
  GsecPanelData,
  GsecTick,
  InTick,
  LinkPanelData,
  MpcPanelData,
  PriceYieldData,
  SpreadPanelData,
  UsTick,
} from '../market/types';

export const US_TICK: UsTick = {
  sim_time: '2026-10-20T05:00:00+00:00',
  curve: {
    '1M': 0.0398,
    '3M': 0.0395,
    '6M': 0.0388,
    '1Y': 0.0371,
    '2Y': 0.0352,
    '3Y': 0.0351,
    '5Y': 0.0362,
    '7Y': 0.0381,
    '10Y': 0.041,
    '20Y': 0.0468,
    '30Y': 0.0472,
  },
  effr: 0.0408,
  effr_target: 0.0408,
  corridor: { lower: 0.04, upper: 0.0425, iorb: 0.0415, on_rrp: 0.04, srf: 0.0425 },
  reserves: 2980,
  on_rrp_balance: 12,
  reserves_ratio: 0.1265,
  fed_assets: 6580,
  qt: { treasury_cap: 0, mbs_cap: 17, halted: false },
  term_premium: 0.0068,
  dollar_index: 121.0,
  selling: [],
  as_of: '2026-10-16',
};

const NSS = { beta0: 0.0699, beta1: -0.015, beta2: -0.0174, beta3: 0.0599, tau1: 0.2867, tau2: 59.03 };

export const GSEC_TICK: GsecTick = {
  points: {
    '3M': 0.0565,
    '6M': 0.0586,
    '1Y': 0.0632,
    '2Y': 0.0669,
    '3Y': 0.0691,
    '5Y': 0.0717,
    '7Y': 0.0726,
    '10Y': 0.0741,
    '14Y': 0.0747,
    '20Y': 0.0774,
    '30Y': 0.078,
  },
  nss: NSS,
  rmse_bp: 3.3,
  repo_shift: 0,
  as_of: '2026-10-12',
  stale: 'STALE 8d',
};

export const IN_TICK: InTick = {
  sim_time: '2026-10-20T05:00:00+00:00',
  time: '2026-10-20T10:30:00+05:30',
  session_open: true,
  corridor: { sdf: 0.0525, repo: 0.055, msf: 0.0575 },
  wacr: 0.0528,
  wacr_today: 0.0531,
  last_print: 0.0533,
  map_rate: 0.0543,
  call: { volume: 6684, high: 0.0541, low: 0.0526, rounds: 5 },
  surplus: 185_873,
  surplus_pct: 0.669,
  ndtl: 27_776_966.67,
  laf: { sdf: 129_048, msf: 0, vrr: 0, vrrr: 56_825 },
  segments: { treps: 0.0514, market_repo: 0.0516, notice: 0.0523, term: 0.0583 },
  tbills: { '3M': 0.0565, '6M': 0.0586, '12M': 0.0632 },
  crr: 0.03,
  pending_crr: null,
  fortnight: { start: '2026-10-16', end: '2026-10-31' },
  rejected_today: 0,
  mode: 'realistic',
  band: { lower: 0.0412, upper: 0.0715 },
  tbills_as_of: '2026-10-12',
  tbills_stale: 'STALE 8d',
  gsec: GSEC_TICK,
  fx: null,
  as_of: '2026-10-18',
};

const SHIFTS = [-100, -50, 0, 50, 100];

export const PY_DATA: PriceYieldData = {
  tenor: '10Y',
  ytm: 0.041,
  price: 100,
  macaulay: 8.29,
  modified: 8.12,
  convexity: 77.4,
  dv01: 0.0812,
  shifts_bp: SHIFTS,
  exact: [0.085, 0.042, 0, -0.04, -0.078],
  duration_only: [0.0812, 0.0406, 0, -0.0406, -0.0812],
  duration_convexity: [0.0851, 0.0416, 0, -0.0396, -0.0773],
};

export const CORRIDOR_DATA: CorridorPanelData = {
  map: { deficit: 0.00253, surplus: -0.00452, midpoint: 0.792, width: 0.954, rmse_bp: 17.4, points: 1045 },
  curve: [
    { surplus_pct: -2, rate: 0.0575 },
    { surplus_pct: 4, rate: 0.0525 },
  ],
  now: { surplus_pct: 0.669, map_rate: 0.0543, wacr: 0.0528 },
  real: [
    { date: '2026-10-15', spread: -0.0012 },
    { date: '2026-10-16', spread: -0.0011 },
  ],
  simulated: [{ date: '2026-10-20', spread: -0.0019 }],
  mode: 'realistic',
  band: { lower: 0.0412, upper: 0.0715 },
  excursions: {
    trading_days: 1214,
    below_sdf: 257,
    above_msf: 80,
    weekdays: 1045,
    weekday_below: 151,
    weekday_above: 70,
    simulated_below: 0.143,
    simulated_above: 0.069,
  },
};

const YEARS = { '3M': 0.25, '6M': 0.5, '1Y': 1, '2Y': 2, '10Y': 10, '30Y': 30 };

export const GSEC_DATA: GsecPanelData = {
  tenors: YEARS,
  close: { ...GSEC_TICK.points },
  close_nss: NSS,
  close_rmse_bp: 3.3,
  as_of: '2026-10-12',
  repo_at_close: 0.055,
  passthrough: {
    kappa: 0.62,
    gamma: 0.348,
    scale: 7,
    half_life_years: 1.12,
    kappa_band: [0.058, 5],
    gamma_band: [-0.059, 0.769],
    beta_10y_band: [0.031, 1.331],
    rmse: 0.092,
    level: 0.9,
    events: [
      { date: '2022-05-04', before: '2022-05-02', change: 0.004, moves: { '10Y': 0.00265 } },
      { date: '2026-10-07', before: '2026-10-06', change: 0.0025, moves: { '10Y': 0.0004 } },
    ],
    estimates: [
      { tenor: '3M', years: 0.25, relative: 1, low: 1, high: 1, day_beta: 0.197 },
      { tenor: '2Y', years: 2, relative: 0.732, low: 0.24, high: 1.94, day_beta: 0.145 },
      { tenor: '10Y', years: 10, relative: 0.653, low: 0.1, high: 1.45, day_beta: 0.129 },
      { tenor: '30Y', years: 30, relative: 0.462, low: 0.04, high: 1.04, day_beta: 0.091 },
    ],
    curve: [
      { years: 0.25, beta: 1, expectations: 0.983, tp: 0.017 },
      { years: 2, beta: 0.729, expectations: 0.608, tp: 0.121 },
      { years: 10, beta: 0.54, expectations: 0.171, tp: 0.37 },
      { years: 30, beta: 0.536, expectations: 0.057, tp: 0.479 },
    ],
  },
  factors: {
    level_sd: 0.00035,
    tp_sd: 0.00025,
    correlation: -0.3,
    days: 880,
    residual_bp: 1.2,
    half_life_days: 125,
  },
  now: GSEC_TICK,
};

export const SPRD_DATA: SpreadPanelData = {
  real: [
    { date: '2026-10-09', india: 0.0738, us: 0.0512 },
    { date: '2026-10-12', india: 0.0741, us: 0.0509 },
  ],
  simulated: [],
  now: { india: 0.0741, us: 0.041, spread: 0.0331 },
  daily_from: '2023-02-13',
  india_as_of: '2026-10-12',
  us_as_of: '2026-10-16',
};

const CONFUSION = [
  [1, 1, 0, 0, 0],
  [0, 4, 3, 0, 0],
  [0, 2, 25, 2, 0],
  [0, 0, 2, 3, 1],
  [0, 0, 0, 1, 2],
];

export const MPC_DATA: MpcPanelData = {
  classes: ['big cut', 'cut', 'hold', 'hike', 'big hike'],
  as_of: '2026-10-20',
  next_meeting: '2026-12-04',
  probabilities: {
    'ordered logit': [0.01, 0.08, 0.71, 0.17, 0.03],
    xgboost: [0.02, 0.1, 0.6, 0.23, 0.05],
    taylor: [0, 0, 0, 1, 0],
  },
  features: [
    { key: 'cpi', label: 'CPI inflation, y/y (%)', now: 5.54, last: 5.1 },
    { key: 'wacr_spread', label: 'WACR − repo, two weeks (bp)', now: -22.4, last: -15.0 },
  ],
  taylor: { prescribed: 0.0752, repo: 0.055, inflation: 0.0554, output_gap: 0.004, r_star: 0.015, pi_star: 0.04 },
  backtest: {
    first: '2018-06-06',
    forecasts: 54,
    models: {
      'ordered logit': { accuracy: 0.65, macro_f1: 0.48, brier: 0.52, confusion: CONFUSION },
      xgboost: { accuracy: 0.6, macro_f1: 0.41, brier: 0.55, confusion: CONFUSION },
      taylor: { accuracy: 0.42, macro_f1: 0.3, brier: 1.16, confusion: CONFUSION },
      'repeat last': { accuracy: 0.57, macro_f1: 0.4, brier: 0.86, confusion: CONFUSION },
      'always hold': { accuracy: 0.54, macro_f1: 0.14, brier: 0.92, confusion: CONFUSION },
    },
    recent: [],
  },
  sample: { first: '2014-06-03', last: '2026-10-07', decisions: 78, counts: [5, 12, 44, 11, 6], off_cycle: 5 },
  core_weights: [{ base: '2012', excluded: { food_beverages: 0.4586 }, rmse: 0.04, months: 180 }],
};

const days = 30;

/** ``n`` Monday-to-Friday dates from ``first`` (an ISO date), as the backend schedules a run. */
function businessDays(first: string, n: number): string[] {
  const out: string[] = [];
  for (let d = new Date(`${first}T00:00:00Z`); out.length < n; d.setUTCDate(d.getUTCDate() + 1)) {
    if (d.getUTCDay() % 6 !== 0) out.push(d.toISOString().slice(0, 10));
  }
  return out;
}
const ramp = (total: number) => Array.from({ length: days }, (_, i) => total * (1 - 0.5 ** ((i + 1) / 5)));

export const LINK_DATA: LinkPanelData = {
  mode: 'run',
  response: 'none',
  responses: ['none', 'vrr', 'omo', 'swap', 'hike'],
  response_labels: {
    none: 'none: RBI lets rates move',
    vrr: 'weekly VRR (VRRR) auctions of the drain so far',
    omo: 'weekly OMO purchases (sales) of the drain not yet offset',
    swap: 'a buy/sell swap of the dollars it expects to sell',
    hike: 'a repo hike',
  },
  nodes: [
    { key: 'fed', label: 'Fed funds', value: 50, unit: 'bp', detail: '' },
    { key: 'us10y', label: 'US 10Y', value: 12, unit: 'bp', detail: "the US simulation's response" },
    { key: 'differential', label: 'IN − US 10Y', value: -9.6, unit: 'bp', detail: 'India 10Y +2.4 bp (spillover 0.20)' },
    { key: 'fpi', label: 'FPI flows', value: -0.96, unit: 'US$ bn', detail: 'over 21 business days' },
    { key: 'rbi', label: "RBI's dollar trades", value: -0.58, unit: 'US$ bn', detail: '60% of the flow; reserves $699.4bn' },
    { key: 'inr', label: 'Rupee', value: 0.08, unit: '%', detail: '₹88.07 per $ (+ is weaker)' },
    { key: 'liquidity', label: 'Rupee liquidity', value: -5100, unit: '₹ cr', detail: '-0.020% of NDTL' },
    { key: 'wacr', label: 'WACR', value: 0.4, unit: 'bp', detail: '3M T-bill +0.2 bp' },
    { key: 'response', label: "RBI's response", value: 0, unit: '₹ cr', detail: 'none: RBI lets rates move' },
  ],
  progress: { day: 5, days, dates: businessDays('2026-10-14', days) },
  path: {
    fpi_bn: ramp(-0.96),
    rbi_bn: ramp(-0.58),
    inr: ramp(0.07).map((v) => 88 + v),
    reserves_bn: ramp(-0.58).map((v) => 700 + v),
    surplus_pct: ramp(-0.02).map((v) => 0.6 + v),
    wacr_bp: ramp(0.4),
    vrr_cr: Array.from({ length: days }, () => 0),
  },
  live: { inr: 88.03, reserves_bn: 699.7, surplus_pct: 0.59, wacr: 0.0528, repo: 0.055, runs: 1 },
  anchors: { inr: 88.0, inr_as_of: '2026-10-19', reserves_bn: 700.0, reserves_as_of: '2026-10-16' },
  estimates: [
    {
      key: 'spillover',
      label: 'India 10Y per US 10Y move',
      value: 0.2,
      low: 0.1,
      high: 0.3,
      used: 0.2,
      n: 190,
      r2: 0.08,
      sample: 'weekly, Feb 2023–Oct 2026',
      method: 'ΔIN10Y on ΔUS10Y',
    },
  ],
  assumptions: { flow_days: 21, half_life_days: 5, response_lag_days: 1, every_days: 5, hike_bp: 25, hike_10y: 0.54, horizon_days: 30 },
};
