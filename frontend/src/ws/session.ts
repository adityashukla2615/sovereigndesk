import { runExport } from '../app/exportPanel';
import { runLayout } from '../app/layoutCommand';
import { exportRequestOf, isCommandReply, isInTick, isUsTick, layoutRequestOf } from '../market/types';
import { useConnection } from '../store/connection';
import { STATIC_DEMO } from '../lib/staticDemo';
import { useMarket } from '../store/market';
import { WsClient, type WsClientOptions, defaultWsUrl } from './client';
import type { ClientMessage, Envelope } from './protocol';
import { StaticClient } from './staticClient';

export const SESSION_TOPICS = ['events', 'status', 'us.tick', 'in.tick'];

/** Market ticks and command replies feed the market store; everything reaches the log store. */
export function route(message: Envelope): void {
  const market = useMarket.getState();
  const { topic, data } = message;
  if (topic === 'us.tick' && isUsTick(data)) market.setUs(data);
  else if (topic === 'in.tick' && isInTick(data)) market.setIndia(data);
  else if (topic === 'command' && isCommandReply(data)) market.applyReply(data);
  useConnection.getState().receive(message);
  if (topic !== 'command' || !isCommandReply(data) || !data.ok) return;
  // LAYOUT and EXPORT run here in the browser, once the backend has checked the request.
  const layout = data.code === 'LAYOUT' ? layoutRequestOf(data.data) : null;
  if (layout) runLayout(layout, send);
  const format = data.code === 'EXPORT' ? exportRequestOf(data.data) : null;
  if (format) void runExport(format);
  // A new run (RESET, LOAD): every panel asks again for what it shows.
  if (data.data?.refresh === true) {
    for (const text of new Set(useMarket.getState().slots.map((s) => s.command))) send({ op: 'command', text });
  }
}

let client: WsClient | StaticClient | null = null;

/** Opens the app's single WebSocket session and wires it to the store. Returns a stop function. */
export function startSession(overrides: Partial<WsClientOptions> = {}): () => void {
  client?.stop();
  const store = useConnection.getState();
  // The static web demo plays back a recording instead of talking to a backend.
  const session = STATIC_DEMO
    ? new StaticClient({ onMessage: route, onStatus: store.setStatus })
    : new WsClient({
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
