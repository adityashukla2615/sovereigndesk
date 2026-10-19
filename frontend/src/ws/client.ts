import { type ClientMessage, type Envelope, parseEnvelope } from './protocol';

export type ConnectionStatus = 'connecting' | 'open' | 'closed';

export interface WsClientOptions {
  url: string;
  onMessage: (message: Envelope) => void;
  onStatus: (status: ConnectionStatus) => void;
  /** Topics to subscribe to on every (re)connect: the server forgets them with the socket. */
  topics?: string[];
  /** Injectable for tests. */
  createSocket?: (url: string) => WebSocket;
  random?: () => number;
}

const BASE_DELAY_MS = 500;
const MAX_DELAY_MS = 15_000;

/** Exponential backoff with "equal jitter": a delay in [d/2, d] where d = min(max, base·2^n). */
export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const ceiling = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt);
  return Math.round(ceiling * (0.5 + random() / 2));
}

export function defaultWsUrl(location: Pick<Location, 'protocol' | 'host'> = window.location) {
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;
}

/** Reconnecting WebSocket. Messages sent while disconnected are queued and flushed on open. */
export class WsClient {
  private readonly options: WsClientOptions;
  private socket: WebSocket | null = null;
  private attempt = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = true;
  private readonly queue: ClientMessage[] = [];

  constructor(options: WsClientOptions) {
    this.options = options;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.retryTimer !== null) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    const socket = this.socket;
    this.socket = null;
    socket?.close();
    this.options.onStatus('closed');
  }

  send(message: ClientMessage): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    } else {
      this.queue.push(message);
    }
  }

  private connect(): void {
    this.options.onStatus('connecting');
    const create = this.options.createSocket ?? ((url: string) => new WebSocket(url));
    const socket = create(this.options.url);
    this.socket = socket;

    socket.onopen = () => {
      this.attempt = 0;
      this.options.onStatus('open');
      const topics = this.options.topics ?? [];
      if (topics.length > 0) socket.send(JSON.stringify({ op: 'subscribe', topics }));
      for (const message of this.queue.splice(0)) socket.send(JSON.stringify(message));
    };
    socket.onmessage = (event: MessageEvent) => {
      if (typeof event.data !== 'string') return;
      const envelope = parseEnvelope(event.data);
      if (envelope) this.options.onMessage(envelope);
    };
    socket.onerror = () => {
      socket.close();
    };
    socket.onclose = () => {
      if (this.socket !== socket) return; // stale socket from before stop()/reconnect
      this.socket = null;
      this.options.onStatus('closed');
      if (!this.stopped) this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    const delay = backoffDelay(this.attempt++, this.options.random);
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }
}
