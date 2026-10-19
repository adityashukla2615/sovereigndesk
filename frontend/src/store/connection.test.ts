import { beforeEach, describe, expect, it } from 'vitest';

import { envelope } from '../test/fakeSocket';
import { LOG_LIMIT, useConnection } from './connection';

describe('connection store', () => {
  beforeEach(() => {
    useConnection.setState({ status: 'closed', log: [], lastSeq: null, gaps: 0 });
  });

  it('counts sequence gaps', () => {
    const { receive } = useConnection.getState();
    receive(envelope('status', 1, {}));
    receive(envelope('echo', 2, {}));
    receive(envelope('echo', 4, {}));
    expect(useConnection.getState().gaps).toBe(1);
  });

  it('forgets the last seq when a new socket opens, since seq restarts', () => {
    const { receive, setStatus } = useConnection.getState();
    receive(envelope('status', 7, {}));
    setStatus('open');
    receive(envelope('status', 1, {}));
    expect(useConnection.getState().gaps).toBe(0);
  });

  it('keeps only the newest LOG_LIMIT messages', () => {
    const { receive } = useConnection.getState();
    for (let seq = 1; seq <= LOG_LIMIT + 5; seq++) receive(envelope('echo', seq, {}));
    const { log } = useConnection.getState();
    expect(log).toHaveLength(LOG_LIMIT);
    expect(log[0]?.seq).toBe(6);
  });
});
