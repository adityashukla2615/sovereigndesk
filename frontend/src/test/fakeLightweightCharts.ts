/**
 * A stand-in for lightweight-charts under jsdom, which has no canvas. It records what each
 * chart was given, so tests can check what a panel draws.
 */

export const ColorType = { Solid: 'solid' } as const;
export const LineStyle = { Solid: 0, Dashed: 2 } as const;
export const LineSeries = { type: 'Line' } as const;

export interface FakeSeries {
  options: Record<string, unknown>;
  data: { time: string; value?: number }[];
  markers: { time: string; text?: string }[];
}

/** Every series drawn since the test started, oldest first. */
export const drawn: FakeSeries[] = [];

interface FakeSeriesApi {
  fake: FakeSeries;
  setData: (data: FakeSeries['data']) => void;
  applyOptions: (options: Record<string, unknown>) => void;
}

export function createChart() {
  return {
    applyOptions: (): undefined => undefined,
    addSeries: (_type: unknown, options: Record<string, unknown>): FakeSeriesApi => {
      const fake: FakeSeries = { options, data: [], markers: [] };
      drawn.push(fake);
      return {
        fake,
        setData: (data) => {
          fake.data = data;
        },
        applyOptions: (more) => {
          fake.options = { ...fake.options, ...more };
        },
      };
    },
    removeSeries: (): undefined => undefined,
    timeScale: () => ({ fitContent: (): undefined => undefined }),
    remove: (): undefined => undefined,
  };
}

export function createSeriesMarkers(series: FakeSeriesApi, markers: FakeSeries['markers'] = []) {
  series.fake.markers = markers;
  return {
    setMarkers: (next: FakeSeries['markers']) => {
      series.fake.markers = next;
    },
    detach: (): undefined => undefined,
  };
}
