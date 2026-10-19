import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FakeSocket, envelope } from '../test/fakeSocket';
import { type ConnectionStatus, WsClient, backoffDelay, defaultWsUrl } from './client';
import type { Envelope } from './protocol';

describe('backoffDelay', () => {
  it('doubles from 500 ms with equal jitter', () => {
    expect(backoffDelay(0, () => 0)).toBe(250);
    expect(backoffDelay(0, () => 1)).toBe(500);
    expect(backoffDelay(3, () => 1)).toBe(4000);
  });

  it('caps at 15 s', () => {
    expect(backoffDelay(20, () => 1)).toBe(15_000);
    expect(backoffDelay(20, () => 0)).toBe(7_500);
  });
});

describe('defaultWsUrl', () => {
  it('follows the page origin and scheme', () => {
    expect(defaultWsUrl({ protocol: 'http:', host: 'localhost:5173' })).toBe('ws://localhost:5173/ws');
    expect(defaultWsUrl({ protocol: 'https:', host: 'desk.example' })).toBe('wss://desk.example/ws');
  });
});

describe('WsClient', () => {
  let statuses: ConnectionStatus[];
  let messages: Envelope[];
  let client: WsClient;

  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    statuses = [];
    messages = [];
    client = new WsClient({
      url: 'ws://test/ws',
      onStatus: (s) => statuses.push(s),
      onMessage: (m) => messages.push(m),
      createSocket: (url) => new FakeSocket(url).asWebSocket(),
      random: () => 1,
    });
  });

  afterEach(() => {
    client.stop();
    vi.useRealTimers();
  });

  it('queues messages until open, then flushes them in order', () => {
    client.start();
    client.send({ op: 'ping' });
    client.send({ op: 'command', text: 'UST' });
    const socket = FakeSocket.latest();
    expect(socket.sent).toEqual([]);

    socket.serverOpen();
    expect(statuses).toEqual(['connecting', 'open']);
    expect(socket.sent.map((s) => JSON.parse(s) as unknown)).toEqual([
      { op: 'ping' },
      { op: 'command', text: 'UST' },
    ]);
  });

  it('delivers well-formed envelopes and drops garbage', () => {
    client.start();
    const socket = FakeSocket.latest();
    socket.serverOpen();
    socket.serverSend('not json');
    socket.serverSend({ topic: 'echo' });
    socket.serverSend(envelope('echo', 1, { text: 'QT 95B' }));
    expect(messages).toEqual([envelope('echo', 1, { text: 'QT 95B' })]);
  });

  it('reconnects with backoff after the server drops', () => {
    client.start();
    FakeSocket.latest().serverOpen();
    FakeSocket.latest().close();
    expect(statuses.at(-1)).toBe('closed');
    expect(FakeSocket.instances).toHaveLength(1);

    vi.advanceTimersByTime(499);
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(2);
    expect(statuses.at(-1)).toBe('connecting');
  });

  it('re-subscribes on every connection, before queued messages', () => {
    client = new WsClient({
      url: 'ws://test/ws',
      topics: ['events'],
      onStatus: (s) => statuses.push(s),
      onMessage: (m) => messages.push(m),
      createSocket: (url) => new FakeSocket(url).asWebSocket(),
      random: () => 1,
    });
    client.start();
    client.send({ op: 'ping' });
    FakeSocket.latest().serverOpen();
    expect(FakeSocket.latest().sent.map((s) => JSON.parse(s) as unknown)).toEqual([
      { op: 'subscribe', topics: ['events'] },
      { op: 'ping' },
    ]);
    FakeSocket.latest().close();
    vi.advanceTimersByTime(500);
    FakeSocket.latest().serverOpen();
    expect(FakeSocket.latest().sent).toEqual([JSON.stringify({ op: 'subscribe', topics: ['events'] })]);
  });

  it('does not reconnect after stop()', () => {
    client.start();
    FakeSocket.latest().serverOpen();
    client.stop();
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(statuses.at(-1)).toBe('closed');
  });
});
