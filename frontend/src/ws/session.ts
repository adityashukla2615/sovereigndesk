import { runLayout } from '../app/layoutCommand';
import { isCommandReply, isInTick, isUsTick, layoutRequestOf } from '../market/types';
import { useConnection } from '../store/connection';
import { useMarket } from '../store/market';
import { WsClient, type WsClientOptions, defaultWsUrl } from './client';
import type { ClientMessage, Envelope } from './protocol';

export const SESSION_TOPICS = ['events', 'status', 'us.tick', 'in.tick'];

/** Market ticks and command replies feed the market store; everything reaches the log store. */
export function route(message: Envelope): void {
  const market = useMarket.getState();
  const { topic, data } = message;
  if (topic === 'us.tick' && isUsTick(data)) market.setUs(data);
  else if (topic === 'in.tick' && isInTick(data)) market.setIndia(data);
  else if (topic === 'command' && isCommandReply(data)) market.applyReply(data);
  useConnection.getState().receive(message);
  // LAYOUT runs here in the browser, once the backend has checked the request.
  if (topic === 'command' && isCommandReply(data) && data.ok && data.code === 'LAYOUT') {
    const request = layoutRequestOf(data.data);
    if (request) runLayout(request, send);
  }
}

let client: WsClient | null = null;

/** Opens the app's single WebSocket session and wires it to the store. Returns a stop function. */
export function startSession(overrides: Partial<WsClientOptions> = {}): () => void {
  client?.stop();
  const store = useConnection.getState();
  const session = new WsClient({
    url: defaultWsUrl(),
    topics: SESSION_TOPICS,
    onMessage: route,
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
