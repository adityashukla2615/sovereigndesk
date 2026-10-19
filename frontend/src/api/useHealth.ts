import { useEffect, useState } from 'react';

import { type Health, apiGet } from './client';

export type HealthState =
  | { kind: 'loading' }
  | { kind: 'ok'; health: Health }
  | { kind: 'down'; error: string };

/** Polls `/api/health`; any failure flips the state to `down` until the next good poll. */
export function useHealth(intervalMs = 15_000): HealthState {
  const [state, setState] = useState<HealthState>({ kind: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    const poll = async () => {
      try {
        const health = await apiGet('/api/health', { signal: controller.signal });
        setState({ kind: 'ok', health });
      } catch (error) {
        if (!controller.signal.aborted) setState({ kind: 'down', error: String(error) });
      }
    };
    void poll();
    const id = setInterval(() => void poll(), intervalMs);
    return () => {
      controller.abort();
      clearInterval(id);
    };
  }, [intervalMs]);

  return state;
}
