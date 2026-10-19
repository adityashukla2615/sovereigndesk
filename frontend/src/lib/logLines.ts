import type { Envelope } from '../ws/protocol';

/** One rendered row of the event log. */
export interface LogLine {
  key: string;
  time: string;
  label: string;
  tone: 'policy' | 'shock' | 'projection' | 'info' | 'warning' | 'ok' | 'fail' | 'system';
  text: string;
}

/** Wire shapes, mirroring backend/app/sim/events.py and backend/app/commands/registry.py. */
interface SimEvent {
  sim_time: string;
  kind: 'policy' | 'shock' | 'projection' | 'info' | 'warning';
  code: string;
  text: string;
}

interface CommandReply {
  ok: boolean;
  code: string;
  message: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isSimEvent(value: unknown): value is SimEvent {
  return isRecord(value) && typeof value.text === 'string' && typeof value.kind === 'string';
}

function isCommandReply(value: unknown): value is CommandReply {
  return isRecord(value) && typeof value.ok === 'boolean' && typeof value.message === 'string';
}

function eventLine(event: SimEvent, key: string): LogLine {
  return {
    key,
    time: event.sim_time.slice(11, 19),
    label: event.code,
    tone: event.kind,
    text: event.text,
  };
}

/** Turn one server envelope into the log rows it should produce (possibly none). */
export function logLines(envelope: Envelope): LogLine[] {
  const key = `${envelope.ts}-${String(envelope.seq)}`;
  const time = envelope.ts.slice(11, 19);
  const { topic, data } = envelope;
  if (topic === 'events') {
    // A subscription first delivers the recent history as an array, then single events.
    const events = Array.isArray(data) ? data.filter(isSimEvent) : isSimEvent(data) ? [data] : [];
    return events.map((event, i) => eventLine(event, `${key}-${String(i)}`));
  }
  if (topic === 'command' && isCommandReply(data)) {
    return [{ key, time, label: data.code || 'CMD', tone: data.ok ? 'ok' : 'fail', text: data.message }];
  }
  if (topic === 'error' && isRecord(data)) {
    return [{ key, time, label: 'ERROR', tone: 'fail', text: String(data.reason) }];
  }
  return [];
}
