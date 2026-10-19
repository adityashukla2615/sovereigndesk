/** Minimal stand-in for the browser WebSocket, driven by hand from tests. */
export class FakeSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeSocket[] = [];

  readonly url: string;
  readyState = FakeSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }

  static latest(): FakeSocket {
    const socket = FakeSocket.instances.at(-1);
    if (!socket) throw new Error('no FakeSocket created yet');
    return socket;
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    if (this.readyState === FakeSocket.CLOSED) return;
    this.readyState = FakeSocket.CLOSED;
    this.onclose?.();
  }

  // --- test drivers
  serverOpen(): void {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }

  serverSend(payload: unknown): void {
    const data = typeof payload === 'string' ? payload : JSON.stringify(payload);
    this.onmessage?.({ data } as MessageEvent);
  }

  asWebSocket(): WebSocket {
    return this as unknown as WebSocket;
  }
}

export function envelope(topic: string, seq: number, data: unknown) {
  return { topic, ts: `2026-10-19T14:30:${String(seq % 60).padStart(2, '0')}+00:00`, seq, data };
}
