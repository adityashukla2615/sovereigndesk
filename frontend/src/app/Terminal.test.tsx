import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { drawn } from '../test/fakeLightweightCharts';
import { FakeSocket, envelope } from '../test/fakeSocket';
import { reply, resetTerminal, sentCommands } from '../test/harness';
import { IN_TICK, US_TICK } from '../test/marketData';
import {
  CALL_DATA,
  CCIL_DATA,
  CORR_DATA,
  DEBT_DATA,
  HELP_CALL_DATA,
  HELP_DATA,
  LAF_DATA,
  NDTL_DATA,
  TAXCAL_DATA,
  TIC_DATA,
} from '../test/terminalData';
import { App } from './App';

vi.mock('../components/Chart', () => ({
  Chart: ({ label }: { label: string }) => <div role="img" aria-label={label} />,
}));

async function openTerminal() {
  const view = render(<App />);
  await screen.findByText('KEY OK');
  const socket = FakeSocket.latest();
  act(() => {
    socket.serverOpen();
    socket.serverSend(envelope('us.tick', 1, US_TICK));
    socket.serverSend(envelope('in.tick', 2, IN_TICK));
  });
  return view;
}

/** Alt+n, as a user moves to slot n before asking for a function there. */
function altKey(key: string) {
  fireEvent.keyDown(window, { key, altKey: true });
}

const region = (n: number, code: string) => screen.getByRole('region', { name: `panel ${String(n)}: ${code}` });

describe('Terminal panels, layouts and keys (Phase 12)', () => {
  beforeEach(resetTerminal);

  it('shows the India money-market panels: CALL, LAF, NDTL and TAXCAL', async () => {
    await openTerminal();
    reply('CALL', CALL_DATA);
    const call = region(1, 'CALL');
    const rates = within(call).getByRole('table', { name: 'money market rates' });
    expect(rates).toHaveTextContent('TREPS · CCIL5.14%-36 bp');
    expect(rates).toHaveTextContent('T-BILL 91D · FBIL5.65%+15 bp');
    expect(within(call).getByRole('table', { name: 'Borrowed' })).toHaveTextContent('PVT-032,500');
    expect(within(call).getByRole('table', { name: 'orders trimmed by participation limits' })).toHaveTextContent(
      'daily cap 1,250 cr',
    );
    await waitFor(() => {
      expect(drawn.length).toBeGreaterThanOrEqual(4); // the rounds and the corridor's three lines
    });
    expect(drawn[0]?.data.map((d) => d.value)).toEqual([5.26, 5.29, 5.33]);

    altKey('2');
    reply('LAF', LAF_DATA);
    const laf = region(2, 'LAF');
    expect(laf).toHaveTextContent('NET LAFabsorbing ₹1.86 lakh cr · 0.67% NDTL');
    expect(within(laf).getByRole('table', { name: 'operations outstanding' })).toHaveTextContent('VRRR (absorbs)56,825');
    expect(within(laf).getByRole('table', { name: 'auctions' })).toHaveTextContent('20/10 09:30 VRRRRBI33,453');
    expect(laf).toHaveTextContent('VRR 4% · VRRR 61%');

    altKey('3');
    reply('NDTL', NDTL_DATA);
    const ndtl = region(3, 'NDTL');
    expect(within(ndtl).getByRole('note')).toHaveTextContent('SYNTHETIC: 4 generated banks');
    const banks = within(ndtl).getByRole('table', { name: 'synthetic banks' });
    expect(within(banks).getAllByRole('row')[1]).toHaveTextContent('PSB-01public sector'); // largest first
    expect(banks).toHaveTextContent('PD-01primary dealer');

    altKey('4');
    reply('TAXCAL', TAXCAL_DATA);
    const tax = region(4, 'TAXCAL');
    const windows = within(tax).getByRole('table', { name: 'tax windows ahead' });
    expect(windows).toHaveTextContent('GST2026-10-20 → 10-21₹35,244 cr');
    expect(windows).toHaveTextContent('Advance tax2026-12-13 → 12-14₹51,370 cr');
    expect(within(tax).getByRole('img', { name: 'Calendar heatmap of WACR minus repo by day' })).toBeInTheDocument();
    expect(tax).toHaveTextContent('TIGHTEST AHEAD (2026-10-22)−₹20,000 cr · VRR 62% likely');
    await waitFor(() => {
      expect(drawn.some((s) => s.markers.some((m) => m.text === 'VRR?'))).toBe(true);
    });
    const marks = drawn.find((s) => s.markers.length > 0)?.markers.map((m) => m.text);
    // RBI's simulated auction, today, then the days ahead where an auction is likelier than not.
    expect(marks).toEqual(['VRRR', 'today', 'VRRR?', 'VRR?']);
  });

  it('draws how the overnight markets settle (CCIL), with its sources', async () => {
    await openTerminal();
    reply('CCIL', CCIL_DATA);
    const ccil = region(1, 'CCIL');
    const diagram = within(ccil).getByRole('img', { name: 'How call money, TREPS and market repo trade and settle' });
    expect(diagram).toHaveTextContent('NDS-CALL 09:00–19:00');
    expect(diagram).toHaveTextContent('no central counterparty');
    const table = within(ccil).getByRole('table', { name: 'how each segment trades and settles' });
    expect(table).toHaveTextContent('Call money [1][2]');
    expect(table).toHaveTextContent('none (unsecured)');
    const sources = within(ccil).getByRole('list', { name: 'sources' });
    expect(within(sources).getAllByRole('link')[1]).toHaveAttribute(
      'href',
      'https://www.rbi.org.in/scripts/PublicationReportDetails.aspx?ID=935',
    );
  });

  it('shows the US panels: DEBT, TIC and CORR', async () => {
    await openTerminal();
    reply('DEBT', DEBT_DATA);
    const debt = region(1, 'DEBT');
    expect(debt).toHaveTextContent('EXTRA COST, YEAR 1+$22bn/yr');
    await waitFor(() => {
      expect(drawn).toHaveLength(2);
    });
    expect(drawn[0]?.data).toHaveLength(12);
    fireEvent.click(within(debt).getByRole('button', { name: '% OF GDP' }));
    expect(drawn[0]?.data[0]?.value).toBeCloseTo(3.15);

    altKey('2');
    reply('TIC', TIC_DATA);
    const tic = region(2, 'TIC');
    const holders = within(tic).getByRole('table', { name: 'foreign holders' });
    expect(within(holders).getAllByRole('row')[1]).toHaveTextContent('1JapanSELLING$1.05tn$1.15tn−$100bn11.5%');
    expect(tic).toHaveTextContent('SOLD IN THE SIMULATION$100bn');

    altKey('3');
    reply('CORR', CORR_DATA);
    const corr = region(3, 'CORR');
    expect(corr).toHaveTextContent('EFFR − IORB-7.0 bp');
    expect(corr).toHaveTextContent('WACR − REPO-22.0 bp');
    expect(corr).toHaveTextContent('CORRIDOR+50 bp wide');
    expect(within(corr).getAllByRole('img')).toHaveLength(2); // both corridors
  });

  it('lists every function in HELP, explains one, and F1 explains the focused panel', async () => {
    await openTerminal();
    reply('HELP', HELP_DATA);
    const help = region(1, 'HELP');
    expect(within(help).getByRole('region', { name: 'INDIA MONEY MARKET' })).toHaveTextContent('CALL India call money');
    expect(within(help).getByRole('region', { name: 'SYSTEM' })).toHaveTextContent('Phase 13 (polish)');
    expect(within(help).getByRole('region', { name: 'keys' })).toHaveTextContent('Alt+Enter');
    fireEvent.click(within(help).getByRole('button', { name: 'CALL' }));
    expect(sentCommands().at(-1)).toBe('HELP CALL');
    reply('HELP', HELP_CALL_DATA, { command: 'HELP CALL' });
    const detail = within(region(1, 'HELP')).getByRole('region', { name: 'help for CALL' });
    fireEvent.click(within(detail).getByRole('button', { name: 'RUN CALL' }));
    expect(sentCommands().at(-1)).toBe('CALL');
    altKey('2'); // the FED panel
    fireEvent.keyDown(window, { key: 'F1' });
    expect(sentCommands().at(-1)).toBe('HELP FED');
  });

  it('saves a layout, restores it and the default, and reopens with the last one', async () => {
    const view = await openTerminal();
    reply('PY', { tenor: '30Y' }, { command: 'PY 30Y' });
    altKey('4');
    reply('CALL', CALL_DATA);
    reply('LAYOUT', { layout: { action: 'save', name: 'RATES' } }, { panel: null });
    const saved = JSON.parse(localStorage.getItem('sovereigndesk.layouts') ?? '{}') as Record<string, { commands: string[] }>;
    expect(saved.RATES?.commands).toEqual(['PY 30Y', 'FED', 'WACR', 'CALL']);

    reply('LAYOUT', { layout: { action: 'default', name: null } }, { panel: null });
    expect(region(4, 'UST')).toBeInTheDocument();
    expect(sentCommands().slice(-4)).toEqual(['PY 10Y', 'FED', 'WACR', 'UST']);

    reply('LAYOUT', { layout: { action: 'load', name: 'RATES' } }, { panel: null });
    expect(region(4, 'CALL')).toBeInTheDocument(); // the panel is in place before its reply
    expect(sentCommands().slice(-4)).toEqual(['PY 30Y', 'FED', 'WACR', 'CALL']);

    const log = screen.getByRole('region', { name: 'event log' });
    reply('LAYOUT', { layout: { action: 'load', name: 'NOPE' } }, { panel: null });
    expect(log).toHaveTextContent('No layout NOPE saved in this browser');
    reply('LAYOUT', { layout: { action: 'list', name: null } }, { panel: null });
    expect(log).toHaveTextContent('Saved in this browser: RATES');
    reply('LAYOUT', { layout: { action: 'delete', name: 'RATES' } }, { panel: null });
    expect(localStorage.getItem('sovereigndesk.layouts')).toBe('{}');

    // The terminal reopens as it was left.
    view.unmount();
    resetTerminal();
    await openTerminal();
    expect(sentCommands()).toEqual(['PY 30Y', 'FED', 'WACR', 'CALL']);
    expect(region(4, 'CALL')).toBeInTheDocument();
  });

  it('moves between panels with Alt+arrows, maximises one, and comes back to the command bar', async () => {
    await openTerminal();
    altKey('ArrowRight');
    expect(document.activeElement).toBe(region(2, 'FED'));
    altKey('ArrowDown');
    expect(document.activeElement).toBe(region(4, 'UST'));
    altKey('ArrowLeft');
    expect(document.activeElement).toBe(region(3, 'WACR'));
    altKey('Enter');
    expect(screen.getAllByRole('region', { name: /^panel / })).toHaveLength(1);
    expect(region(3, 'WACR')).toHaveTextContent('MAX · Alt+Enter');
    altKey('Enter');
    expect(screen.getAllByRole('region', { name: /^panel / })).toHaveLength(4);
    fireEvent.keyDown(region(3, 'WACR'), { key: 'Escape' });
    expect(document.activeElement).toBe(screen.getByRole('combobox', { name: 'command' }));
    altKey('t');
    expect(sentCommands().at(-1)).toBe('TEACH');
  });
});
