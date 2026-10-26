/** A terminal under test: the REST answers it starts with and fresh stores before each test. */

import { act } from '@testing-library/react';
import { vi } from 'vitest';

import type { Health } from '../api/client';
import type { SimStatus } from '../api/useSim';
import type { CommandInfo } from '../market/types';
import { useConnection } from '../store/connection';
import { useLayout } from '../store/layouts';
import { initialSlots, useMarket } from '../store/market';
import { FakeSocket, envelope } from './fakeSocket';

export const HEALTH: Health = {
  status: 'ok',
  version: '0.1.0',
  engine_version: '0.1.0',
  time: '2026-10-19T14:30:00Z',
  offline: false,
  fred_key_configured: true,
};

export const SIM: SimStatus = {
  running: true,
  error: null,
  paused: false,
  speed: 1,
  sim_time: '2026-10-20T05:00:00+00:00',
  anchored_as_of: '2026-10-16',
  input_quality: ['SEED 2026-10-19'],
  india: { running: true, error: null, anchored_as_of: '2026-10-18', input_quality: ['LIVE'] },
};

export const COMMANDS: CommandInfo[] = [
  { code: 'QT', usage: 'QT 95B | QT OFF', summary: 'Set the monthly runoff', group: 'US', available: true, available_in: null },
];

function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
  if (url.endsWith('/api/sim/status')) return Promise.resolve(Response.json(SIM));
  if (url.endsWith('/api/commands')) return Promise.resolve(Response.json(COMMANDS));
  return Promise.resolve(Response.json(HEALTH));
}

/** Fresh stores, a fake socket class and fetch: call in `beforeEach`. */
export function resetTerminal(): void {
  FakeSocket.instances = [];
  useConnection.setState({ status: 'closed', log: [], lastSeq: null, gaps: 0 });
  useMarket.setState({
    us: null,
    india: null,
    usBefore: null,
    indiaBefore: null,
    slots: initialSlots(),
    focused: 0,
    teach: false,
  });
  useLayout.setState({ sizes: {}, version: 0, maximized: null });
  vi.stubGlobal('WebSocket', FakeSocket);
  vi.stubGlobal('fetch', vi.fn(fakeFetch));
}

let seq = 100;

/** The server replies to a command, as the backend would. */
export function reply(
  code: string,
  data: unknown,
  { panel = code, message = `${code} reply`, command = code }: { panel?: string | null; message?: string; command?: string } = {},
): void {
  const socket = FakeSocket.latest();
  act(() => {
    seq += 1;
    socket.serverSend(envelope('command', seq, { ok: true, code, message, panel, data, command }));
  });
}

/** The commands the terminal has sent, in order. */
export function sentCommands(): string[] {
  return FakeSocket.latest()
    .sent.map((s) => JSON.parse(s) as { op: string; text?: string })
    .filter((m) => m.op === 'command')
    .map((m) => m.text ?? '');
}
