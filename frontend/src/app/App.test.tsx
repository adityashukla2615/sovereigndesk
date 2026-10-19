import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Health } from '../api/client';
import { useConnection } from '../store/connection';
import { FakeSocket, envelope } from '../test/fakeSocket';
import { App } from './App';

const HEALTH: Health = {
  status: 'ok',
  version: '0.1.0',
  engine_version: '0.1.0',
  time: '2026-10-19T14:30:00Z',
  offline: false,
  fred_key_configured: true,
};

describe('App shell', () => {
  beforeEach(() => {
    FakeSocket.instances = [];
    useConnection.setState({ status: 'closed', log: [], lastSeq: null, gaps: 0 });
    vi.stubGlobal('WebSocket', FakeSocket);
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(Response.json(HEALTH))),
    );
  });

  it('shows backend health and connection status', async () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: 'SOVEREIGNDESK' })).toBeInTheDocument();
    expect(await screen.findByText('KEY OK')).toBeInTheDocument();
    const status = screen.getByRole('status', { name: 'system status' });
    expect(status).toHaveTextContent('APIv0.1.0');
    expect(status).toHaveTextContent('ENGINEv0.1.0');
    expect(status).toHaveTextContent('MODEONLINE');
    expect(screen.getByText(/CONNECTING/)).toBeInTheDocument();

    act(() => {
      FakeSocket.latest().serverOpen();
    });
    expect(screen.getByText(/LIVE/)).toBeInTheDocument();
  });

  it('sends commands over the socket and logs the echo', async () => {
    render(<App />);
    await screen.findByText('KEY OK');
    const socket = FakeSocket.latest();
    act(() => {
      socket.serverOpen();
    });

    const input = screen.getByRole('textbox', { name: 'command' });
    fireEvent.change(input, { target: { value: '  QT 95B ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(input).toHaveValue('');
    expect(socket.sent.map((s) => JSON.parse(s) as unknown)).toEqual([
      { op: 'command', text: 'QT 95B' },
    ]);

    act(() => {
      socket.serverSend(envelope('echo', 1, { text: 'QT 95B' }));
    });
    expect(screen.getByRole('region', { name: 'event log' })).toHaveTextContent('QT 95B');

    fireEvent.keyDown(input, { key: 'ArrowUp' });
    expect(input).toHaveValue('QT 95B');
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
