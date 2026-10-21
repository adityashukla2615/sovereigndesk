import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

import { drawn } from './fakeLightweightCharts';

// jsdom has no canvas: lightweight-charts is replaced by a recorder of what each chart is given.
vi.mock('lightweight-charts', () => import('./fakeLightweightCharts'));

afterEach(() => {
  cleanup();
  drawn.length = 0;
});

// jsdom has no layout, so no ResizeObserver; the resizable panels construct one.
class NoopResizeObserver {
  observe = (): undefined => undefined;
  unobserve = (): undefined => undefined;
  disconnect = (): undefined => undefined;
}
if (!('ResizeObserver' in globalThis)) {
  Object.defineProperty(globalThis, 'ResizeObserver', { value: NoopResizeObserver, writable: true });
}
