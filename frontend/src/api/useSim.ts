import { useEffect, useState } from 'react';

import type { CommandInfo } from '../market/types';
import { type GetResponse, apiGet } from './client';

export type SimStatus = GetResponse<'/api/sim/status'>;

/** Polls `/api/sim/status` (speed, pause, data quality); null until the first good answer. */
export function useSimStatus(intervalMs = 5_000): SimStatus | null {
  const [status, setStatus] = useState<SimStatus | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const poll = async () => {
      try {
        const next = await apiGet('/api/sim/status', { signal: controller.signal });
        if (typeof next.running === 'boolean') setStatus(next);
      } catch {
        // The status strip keeps the last good answer; the WS and API fields show outages.
      }
    };
    void poll();
    const id = setInterval(() => void poll(), intervalMs);
    return () => {
      controller.abort();
      clearInterval(id);
    };
  }, [intervalMs]);
  return status;
}

/** The function catalogue for autocomplete, fetched once (the backend registry is the source). */
export function useCommands(): CommandInfo[] {
  const [commands, setCommands] = useState<CommandInfo[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    apiGet('/api/commands', { signal: controller.signal })
      .then((list) => {
        if (Array.isArray(list)) setCommands(list);
      })
      .catch(() => {
        // Without the catalogue the command bar still works, just without suggestions.
      });
    return () => {
      controller.abort();
    };
  }, []);
  return commands;
}
