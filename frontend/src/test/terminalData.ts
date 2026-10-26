/** Replies for the Phase 12 panels, shaped like the backend's (see market/types.ts). */

import type {
  CallPanelData,
  CcilPanelData,
  CommandInfo,
  CorrPanelData,
  DebtPanelData,
  HelpPanelData,
  LafPanelData,
  NdtlPanelData,
  TaxcalPanelData,
  TicPanelData,
} from '../market/types';

export const CALL_DATA: CallPanelData = {
  time: '2026-10-20T10:30:00+05:30',
  rounds: [
    { time: '09:15', rate: 0.0526, volume: 1200 },
    { time: '09:30', rate: 0.0529, volume: 1500 },
    { time: '09:45', rate: 0.0533, volume: 1300 },
  ],
  borrowers: [
    { bank: 'PVT-03', amount: 2500 },
    { bank: 'SFB-02', amount: 900 },
  ],
  lenders: [{ bank: 'PSB-01', amount: 3100 }],
  rejections: [
    { time: '09:30', bank: 'SFB-02', side: 'borrow', amount: 400, reason: 'daily cap 1,250 cr would be exceeded (1,650 cr)' },
  ],
  segments: { treps: 0.0514, market_repo: 0.0516, notice: 0.0523, term: 0.0583 },
  segment_volumes: { call: 6684, treps: 185_147, market_repo: 75_529, notice: 117, term: 334 },
};

export const LAF_DATA: LafPanelData = {
  sdf: 129_048,
  msf: 0,
  operations: [{ kind: 'VRRR', amount: 56_825, rate: 0.0549, start: '2026-10-16', maturity: '2026-10-23' }],
  auctions: [
    {
      time: '2026-10-20T09:30:00+05:30',
      kind: 'VRRR',
      notified: 33_453,
      received: 41_200,
      allotted: 33_453,
      cut_off: 0.0547,
      weighted_average: 0.0545,
      tenor_days: 1,
      manual: false,
    },
  ],
  surplus: 185_873,
  surplus_pct: 0.669,
  durable_liquidity: 312_000,
  durable_as_of: '2026-10-10',
  reaction: { enabled: true, vrr_probability: 0.04, vrrr_probability: 0.61, vrr_size: 34_528, vrrr_size: 33_453 },
};

function bank(code: string, kind: string, ndtl: number, extra: Partial<NdtlPanelData['banks'][number]> = {}) {
  return {
    code,
    kind,
    ndtl,
    capital_funds: ndtl * 0.1,
    requirement: ndtl * 0.03,
    balance: ndtl * 0.031,
    target: ndtl * 0.03,
    slr_holdings: ndtl * 0.2,
    msf_capacity: ndtl * 0.04,
    borrowed: 0,
    lent: 0,
    borrow_cap_avg: ndtl * 0.1,
    borrow_cap_peak: ndtl * 0.125,
    floor_breaches: 0,
    ...extra,
  };
}

export const NDTL_DATA: NdtlPanelData = {
  synthetic: true,
  banks: [
    bank('PVT-03', 'PVT', 900_000, { borrowed: 2500 }),
    bank('PSB-01', 'PSB', 2_400_000, { lent: 3100 }),
    bank('SFB-02', 'SFB', 60_000, { balance: 1000, floor_breaches: 1 }),
    { ...bank('PD-01', 'PD', 0), capital_funds: 2500, slr_holdings: 9000, borrowed: 2400 },
  ],
};

export const TAXCAL_DATA: TaxcalPanelData = {
  real: [
    { date: '2026-09-14', spread: -0.0004 },
    { date: '2026-09-15', spread: 0.0018 },
    { date: '2026-09-16', spread: 0.0021 },
  ],
  simulated: [
    { date: '2026-10-19', spread: -0.0021, surplus: 190_000, surplus_pct: 0.68, government: 0, vrr: 0, vrrr: 33_453 },
  ],
  tax_days: [
    { date: '2026-10-20', drain: 17_622 },
    { date: '2026-10-21', drain: 17_622 },
    { date: '2026-12-13', drain: 25_685 },
    { date: '2026-12-14', drain: 25_685 },
    { date: '2026-12-18', drain: 17_622 },
  ],
  projection: [
    { date: '2026-10-21', government: 17_622, surplus: 168_251, surplus_pct: 0.6, p_vrr: 0.05, p_vrrr: 0.55 },
    { date: '2026-10-22', government: 35_244, surplus: -20_000, surplus_pct: -0.07, p_vrr: 0.62, p_vrrr: 0.1 },
  ],
  now: { date: '2026-10-20', government: 0, surplus: 185_873, surplus_pct: 0.669 },
  tax: { advance_tax_drain: 128_425, gst_drain: 88_109, events: 54, hold_days: 10, return_days: 14 },
  reaction: { enabled: true, vrr_size: 34_528, vrrr_size: 33_453 },
};

const SOURCES = [
  {
    claim: 'NDS-CALL is an electronic request-for-quote platform owned by RBI and managed by Clearcorp.',
    document: 'CCIL, Clearcorp Dealing Systems',
    url: 'https://www.ccilindia.com/clearcorp-dealing-systems',
  },
  {
    claim: 'Call money is settled bilaterally through RTGS, throughout the day.',
    document: 'RBI, Working Group on trading and settlement timings',
    url: 'https://www.rbi.org.in/scripts/PublicationReportDetails.aspx?ID=935',
  },
];

export const CCIL_DATA: CcilPanelData = {
  segments: [
    {
      key: 'call',
      name: 'Call money',
      platform: 'NDS-CALL',
      dealing: 'Request for quote between named banks',
      collateral: null,
      counterparty: 'The other bank: unsecured',
      settlement: 'Bilaterally through RTGS, during the day',
      hours: ['09:00', '19:00'],
      sources: [0, 1],
      rate: 0.0528,
      volume: 6684,
    },
    {
      key: 'treps',
      name: 'TREPS (tri-party repo)',
      platform: 'TREPS',
      dealing: 'Anonymous order matching',
      collateral: 'Government securities',
      counterparty: 'CCIL, as central counterparty',
      settlement: 'Netted by CCIL',
      hours: ['09:00', '16:00'],
      sources: [0, 1],
      rate: 0.0514,
      volume: 185_147,
    },
    {
      key: 'market_repo',
      name: 'Market repo',
      platform: 'CROMS',
      dealing: 'Anonymous order matching',
      collateral: 'Government securities, sold and bought back',
      counterparty: 'CCIL, as central counterparty',
      settlement: 'Netted by CCIL',
      hours: ['09:00', '16:00'],
      sources: [0, 1],
      rate: 0.0516,
      volume: 75_529,
    },
  ],
  also_on_nds_call: { notice: { rate: 0.0523, volume: 117 }, term: { rate: 0.0583, volume: 334 } },
  repo: 0.055,
  time: '2026-10-20T10:30:00+05:30',
  session_open: true,
  model: 'Rates and volumes are the simulated day’s.',
  sources: SOURCES,
};

export const DEBT_DATA: DebtPanelData = {
  start: '2026-09-30',
  months: Array.from({ length: 12 }, (_, i) => {
    const month = 9 + i; // October 2026 onwards, counted from January 2026 = 0
    return `${String(2026 + Math.floor(month / 12))}-${String((month % 12) + 1).padStart(2, '0')}-01`;
  }),
  baseline_interest: Array.from({ length: 12 }, (_, i) => 1000 + i),
  shocked_interest: Array.from({ length: 12 }, (_, i) => 1000 + 3 * i),
  baseline_to_gdp: Array.from({ length: 12 }, () => 0.031),
  shocked_to_gdp: Array.from({ length: 12 }, () => 0.0315),
  baseline_to_receipts: Array.from({ length: 12 }, () => 0.18),
  shocked_to_receipts: Array.from({ length: 12 }, () => 0.185),
  delta_by_year: { '1': 22 },
};

export const TIC_DATA: TicPanelData = {
  as_of: '2026-08-31',
  holders: [
    { country: 'Japan', holdings: 1050.3, official: 1150.3, selling: true },
    { country: 'United Kingdom', holdings: 865.0, official: 865.0, selling: false },
    { country: 'China, Mainland', holdings: 700.2, official: 700.2, selling: false },
  ],
  total: 9100.0,
  official_total: 9200.0,
};

export const CORR_DATA: CorrPanelData = {
  us: { lower: 0.04, upper: 0.0425, iorb: 0.0415, on_rrp: 0.04, effr: 0.0408 },
  india: { sdf: 0.0525, repo: 0.055, msf: 0.0575, wacr: 0.0528 },
};

const CALL_INFO: CommandInfo = {
  code: 'CALL',
  usage: 'CALL',
  summary: 'India call money market today',
  group: 'IN',
  available: true,
  available_in: null,
};

const HELP_COMMANDS: CommandInfo[] = [
  { code: 'UST', usage: 'UST', summary: 'US Treasury par curve', group: 'US', available: true, available_in: null },
  { code: 'SHOCK', usage: 'SHOCK JP 200B [10D]', summary: 'A foreign holder sells', group: 'US', available: true, available_in: null },
  CALL_INFO,
  { code: 'LINK', usage: 'LINK', summary: 'US → India linkage', group: 'X', available: true, available_in: null },
  { code: 'SAVE', usage: 'SAVE name', summary: 'Save the current scenario', group: 'SYS', available: false, available_in: 'Phase 13 (polish)' },
];

export const HELP_DATA: HelpPanelData = { commands: HELP_COMMANDS };

export const HELP_CALL_DATA: HelpPanelData = { commands: HELP_COMMANDS, command: CALL_INFO };
