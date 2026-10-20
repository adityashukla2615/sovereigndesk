/** Tick and panel payloads shaped like the backend's, for component tests. */

import type { CorridorPanelData, InTick, PriceYieldData, UsTick } from '../market/types';

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
};
