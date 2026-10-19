import { useConnection } from '../store/connection';
import { WsClient, type WsClientOptions, defaultWsUrl } from './client';
import type { ClientMessage } from './protocol';

let client: WsClient | null = null;

/** Opens the app's single WebSocket session and wires it to the store. Returns a stop function. */
export function startSession(overrides: Partial<WsClientOptions> = {}): () => void {
  client?.stop();
  const store = useConnection.getState();
  const session = new WsClient({
    url: defaultWsUrl(),
    topics: ['events', 'status'],
    onMessage: store.receive,
    onStatus: store.setStatus,
    ...overrides,
  });
  client = session;
  session.start();
  return () => {
    session.stop();
    if (client === session) client = null;
  };
}

export function send(message: ClientMessage): void {
  client?.send(message);
}
