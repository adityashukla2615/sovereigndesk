import { create } from 'zustand';

import type { ConnectionStatus } from '../ws/client';
import type { Envelope } from '../ws/protocol';

export const LOG_LIMIT = 200;
export const TICK_TOPICS: ReadonlySet<string> = new Set(['us.tick', 'in.tick']);

interface ConnectionState {
  status: ConnectionStatus;
  /** Most recent server messages, oldest first, capped at LOG_LIMIT. */
  log: Envelope[];
  lastSeq: number | null;
  /** Count of sequence gaps seen (a skipped `seq` means a dropped message). */
  gaps: number;
  setStatus: (status: ConnectionStatus) => void;
  receive: (message: Envelope) => void;
  /** A line from the terminal itself (e.g. the saved layouts), logged like a command reply. */
  note: (code: string, message: string, ok: boolean) => void;
}

let notes = 0;

export const useConnection = create<ConnectionState>()((set) => ({
  status: 'closed',
  log: [],
  lastSeq: null,
  gaps: 0,
  // `seq` restarts on every connection, so forget the last one when a socket opens.
  setStatus: (status) => {
    set(status === 'open' ? { status, lastSeq: null } : { status });
  },
  receive: (message) => {
    set((state) => ({
      // Market ticks arrive at 4 Hz: they feed the market store, not the event log.
      log: TICK_TOPICS.has(message.topic) ? state.log : [...state.log, message].slice(-LOG_LIMIT),
      lastSeq: message.seq,
      gaps: state.lastSeq !== null && message.seq !== state.lastSeq + 1 ? state.gaps + 1 : state.gaps,
    }));
  },
  // Local lines take negative sequence numbers: they never count as the server's.
  note: (code, message, ok) => {
    notes += 1;
    const line: Envelope = { topic: 'command', ts: new Date().toISOString(), seq: -notes, data: { ok, code, message } };
    set((state) => ({ log: [...state.log, line].slice(-LOG_LIMIT) }));
  },
}));
