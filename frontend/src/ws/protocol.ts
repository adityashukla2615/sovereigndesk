/** Wire protocol for `/ws`. Mirrors backend/app/ws/protocol.py; keep the two in step. */

export type ClientMessage =
  | { op: 'subscribe'; topics: string[] }
  | { op: 'command'; text: string }
  | { op: 'ping' };

export interface Envelope<T = unknown> {
  topic: string;
  /** ISO-8601 UTC timestamp set by the server. */
  ts: string;
  /** Strictly increasing per connection; restarts at 1 on reconnect. */
  seq: number;
  data: T;
}

export function parseEnvelope(raw: string): Envelope | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== 'object' || value === null || !('data' in value)) return null;
  const { topic, ts, seq, data } = value as Record<string, unknown>;
  if (typeof topic !== 'string' || typeof ts !== 'string' || typeof seq !== 'number') return null;
  return { topic, ts, seq, data };
}
