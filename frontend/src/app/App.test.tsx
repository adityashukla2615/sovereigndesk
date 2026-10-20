import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Health } from '../api/client';
import type { SimStatus } from '../api/useSim';
import type { CommandInfo } from '../market/types';
import { useConnection } from '../store/connection';
import { initialSlots, useMarket } from '../store/market';
import { FakeSocket, envelope } from '../test/fakeSocket';
import { GSEC_DATA, IN_TICK, LINK_DATA, MPC_DATA, PY_DATA, SPRD_DATA, US_TICK } from '../test/marketData';
import { App } from './App';

vi.mock('../components/Chart', () => ({
  Chart: ({ label }: { label: string }) => <div role="img" aria-label={label} />,
}));

const HEALTH: Health = {
  status: 'ok',
  version: '0.1.0',
  engine_version: '0.1.0',
  time: '2026-10-19T14:30:00Z',
  offline: false,
  fred_key_configured: true,
};

const SIM: SimStatus = {
  running: true,
  error: null,
  paused: false,
  speed: 1,
  sim_time: '2026-10-20T05:00:00+00:00',
  anchored_as_of: '2026-10-16',
  input_quality: ['SEED 2026-10-19'],
  india: { running: true, error: null, anchored_as_of: '2026-10-18', input_quality: ['LIVE'] },
};

const COMMANDS: CommandInfo[] = [
  { code: 'QT', usage: 'QT 95B | QT OFF', summary: 'Set the monthly runoff', group: 'US', available: true, available_in: null },
  { code: 'MPC', usage: 'MPC', summary: 'Next MPC decision', group: 'IN', available: false, available_in: 'Phase 8 (MPC predictor)' },
];

function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
  if (url.endsWith('/api/sim/status')) return Promise.resolve(Response.json(SIM));
  if (url.endsWith('/api/commands')) return Promise.resolve(Response.json(COMMANDS));
  return Promise.resolve(Response.json(HEALTH));
}

describe('App terminal', () => {
  beforeEach(() => {
    FakeSocket.instances = [];
    useConnection.setState({ status: 'closed', log: [], lastSeq: null, gaps: 0 });
    useMarket.setState({ us: null, india: null, usBefore: null, indiaBefore: null, slots: initialSlots(), focused: 0, teach: false });
    vi.stubGlobal('WebSocket', FakeSocket);
    vi.stubGlobal('fetch', vi.fn(fakeFetch));
  });

  it('shows backend health, simulator status and data quality', async () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: 'SOVEREIGNDESK' })).toBeInTheDocument();
    expect(await screen.findByText('KEY OK')).toBeInTheDocument();
    const status = screen.getByRole('status', { name: 'system status' });
    expect(status).toHaveTextContent('APIv0.1.0');
    expect(await within(status).findByText('US SEED 2026-10-19')).toBeInTheDocument();
    expect(within(status).getByText('IN LIVE')).toBeInTheDocument();
    expect(status).toHaveTextContent('SIM1×');
    act(() => {
      FakeSocket.latest().serverOpen();
    });
    expect(screen.getAllByText(/LIVE/).length).toBeGreaterThan(0);
  });

  it('subscribes, fills the panels at startup and routes replies and ticks', async () => {
    render(<App />);
    await screen.findByText('KEY OK');
    const socket = FakeSocket.latest();
    act(() => {
      socket.serverOpen();
    });
    const input = screen.getByRole('combobox', { name: 'command' });
    fireEvent.change(input, { target: { value: '  QT 95B ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(input).toHaveValue('');
    expect(socket.sent.map((s) => JSON.parse(s) as unknown)).toEqual([
      { op: 'subscribe', topics: ['events', 'status', 'us.tick', 'in.tick'] },
      { op: 'command', text: 'PY 10Y' },
      { op: 'command', text: 'FED' },
      { op: 'command', text: 'WACR' },
      { op: 'command', text: 'UST' },
      { op: 'command', text: 'QT 95B' },
    ]);

    act(() => {
      socket.serverSend(envelope('us.tick', 1, US_TICK));
      socket.serverSend(envelope('in.tick', 2, IN_TICK));
      socket.serverSend(
        envelope('command', 3, { ok: true, code: 'PY', message: '10Y par bond at 4.10%', panel: 'PY', data: PY_DATA }),
      );
      socket.serverSend(
        envelope('events', 4, {
          sim_time: '2026-10-19T14:05:00+00:00',
          kind: 'projection',
          code: 'QT',
          text: 'over 24 months reserves fall',
          data: {},
        }),
      );
    });
    const py = screen.getByRole('region', { name: 'panel 1: PY' });
    expect(py).toHaveTextContent('MOD DURATION8.12');
    expect(within(py).getByRole('img', { name: '10Y price against yield change' })).toBeInTheDocument();
    const tape = screen.getByRole('marquee', { name: 'ticker' });
    expect(tape).toHaveTextContent('UST 10Y4.100%');
    expect(tape).toHaveTextContent('WACR5.28%');
    const wacrPanel = screen.getByRole('region', { name: 'panel 3: WACR' });
    expect(wacrPanel).toHaveTextContent('SURPLUS₹1.86 lakh cr');
    expect(within(wacrPanel).getByText('STALE 8d')).toBeInTheDocument(); // week-old FBIL T-bills
    expect(tape).toHaveTextContent('TB 3M5.65% STALE 8d');
    fireEvent.click(within(wacrPanel).getByRole('button', { name: /REALISTIC/ }));
    expect(JSON.parse(socket.sent.at(-1) ?? '{}')).toEqual({ op: 'command', text: 'WACR POLICY' });
    const log = screen.getByRole('region', { name: 'event log' });
    expect(log).toHaveTextContent('10Y par bond at 4.10%');
    expect(log).toHaveTextContent('over 24 months reserves fall');
    expect(log).not.toHaveTextContent('us.tick');

    fireEvent.keyDown(input, { key: 'ArrowUp' });
    expect(input).toHaveValue('QT 95B');
  });

  it('opens the G-sec curve and the spread to Treasuries', async () => {
    render(<App />);
    await screen.findByText('KEY OK');
    const socket = FakeSocket.latest();
    act(() => {
      socket.serverOpen();
      socket.serverSend(envelope('us.tick', 1, US_TICK));
      socket.serverSend(envelope('in.tick', 2, IN_TICK));
      socket.serverSend(
        envelope('command', 3, { ok: true, code: 'GSEC', message: 'G-secs: 91D 5.65%', panel: 'GSEC', data: GSEC_DATA }),
      );
    });
    const gsec = screen.getByRole('region', { name: 'panel 1: GSEC' });
    expect(gsec).toHaveTextContent('10Y7.410% (+0.0 bp)');
    expect(gsec).toHaveTextContent('2Y 0.73 · 10Y 0.54');
    expect(within(gsec).getByText('STALE 8d')).toBeInTheDocument(); // FBIL's workbook lags a week
    expect(await within(gsec).findByRole('img', { name: /G-sec curve/ })).toBeInTheDocument();
    expect(within(gsec).getByRole('img', { name: /Repo pass-through/ })).toBeInTheDocument();
    const tape = screen.getByRole('marquee', { name: 'ticker' });
    expect(tape).toHaveTextContent('IN 10Y7.410%');
    expect(tape).toHaveTextContent('IN–US 10Y+331 bp');

    act(() => {
      useMarket.getState().focus(1);
      socket.serverSend(
        envelope('command', 4, { ok: true, code: 'SPRD', message: 'India 10Y 7.41%', panel: 'SPRD', data: SPRD_DATA }),
      );
    });
    const sprd = screen.getByRole('region', { name: 'panel 2: SPRD' });
    expect(sprd).toHaveTextContent('INDIA − US+331 bp');
    expect(sprd).toHaveTextContent('REAL ON 2026-10-12+232 bp');
    expect(await within(sprd).findByRole('img', { name: /India 10Y against US 10Y/ })).toBeInTheDocument();
  });

  it('shows the MPC forecast, its backtest and refreshes on request', async () => {
    render(<App />);
    await screen.findByText('KEY OK');
    const socket = FakeSocket.latest();
    act(() => {
      socket.serverOpen();
      socket.serverSend(
        envelope('command', 1, { ok: true, code: 'MPC', message: 'Next MPC decision', panel: 'MPC', data: MPC_DATA }),
      );
    });
    const mpc = screen.getByRole('region', { name: 'panel 1: MPC' });
    expect(mpc).toHaveTextContent('2026-12-04 (in 45d)');
    expect(mpc).toHaveTextContent('HOLD 71%');
    expect(within(mpc).getByRole('table', { name: 'backtest' })).toHaveTextContent('always hold54%0.140.92');
    expect(within(mpc).getByRole('table', { name: 'ordered logit confusion matrix' })).toBeInTheDocument();
    fireEvent.click(within(mpc).getByRole('button', { name: 'xgboost' }));
    expect(within(mpc).getByRole('table', { name: 'xgboost confusion matrix' })).toBeInTheDocument();
    fireEvent.click(within(mpc).getByRole('button', { name: /2026-10-20/ }));
    expect(JSON.parse(socket.sent.at(-1) ?? '{}')).toEqual({ op: 'command', text: 'MPC' });
  });

  it('shows the US → India chain with live rupee and reserves, and runs a shock', async () => {
    render(<App />);
    await screen.findByText('KEY OK');
    const socket = FakeSocket.latest();
    act(() => {
      socket.serverOpen();
      socket.serverSend(envelope('in.tick', 1, { ...IN_TICK, fx: { inr: 88.05, reserves_bn: 699.6, runs: 1 } }));
      socket.serverSend(
        envelope('command', 2, { ok: true, code: 'LINK', message: 'SHOCK FED +50 bp', panel: 'LINK', data: LINK_DATA }),
      );
    });
    const link = screen.getByRole('region', { name: 'panel 1: LINK' });
    expect(link).toHaveTextContent('day 5 of 30');
    expect(link).toHaveTextContent('₹88.05/$'); // the live tick, not the run's start
    const chain = within(link).getByRole('list', { name: 'transmission chain' });
    expect(within(chain).getAllByRole('listitem')).toHaveLength(9);
    expect(within(chain).getByLabelText('FPI flows: −$0.96bn')).toBeInTheDocument();
    expect(within(chain).getByLabelText('Rupee liquidity: −₹5,100 cr')).toBeInTheDocument();
    expect(within(link).getByRole('table', { name: 'calibration' })).toHaveTextContent('0.10…0.30');
    fireEvent.click(within(link).getByRole('button', { name: 'VRR' }));
    expect(JSON.parse(socket.sent.at(-1) ?? '{}')).toEqual({ op: 'command', text: 'LINK VRR' });
    fireEvent.click(within(link).getByRole('button', { name: 'RUN SHOCK FED 50BP' }));
    expect(JSON.parse(socket.sent.at(-1) ?? '{}')).toEqual({ op: 'command', text: 'SHOCK FED 50BP' });
  });

  it('suggests functions while a code is typed and completes with Tab', async () => {
    render(<App />);
    const input = screen.getByRole('combobox', { name: 'command' });
    await screen.findByText('KEY OK');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'q' } });
    const list = await screen.findByRole('listbox');
    expect(list).toHaveTextContent('QT 95B | QT OFF');
    fireEvent.keyDown(input, { key: 'Tab' });
    expect(input).toHaveValue('QT ');
  });

  it('toggles teach notes and focuses panels from the keyboard', async () => {
    render(<App />);
    await screen.findByText('KEY OK');
    const socket = FakeSocket.latest();
    act(() => {
      socket.serverOpen();
      socket.serverSend(envelope('command', 1, { ok: true, code: 'PY', message: 'ok', panel: 'PY', data: PY_DATA }));
      socket.serverSend(envelope('command', 2, { ok: true, code: 'TEACH', message: 'Teach mode toggled', panel: 'TEACH', data: null }));
    });
    expect(screen.getByRole('complementary', { name: 'teach note for PY' })).toHaveTextContent('Convexity');
    fireEvent.keyDown(window, { key: '3', altKey: true });
    expect(useMarket.getState().focused).toBe(2);
  });

  it('flags the API as down when health fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('network down'))),
    );
    render(<App />);
    expect(await screen.findByText('DOWN', { selector: '[title]' })).toBeInTheDocument();
  });
});
