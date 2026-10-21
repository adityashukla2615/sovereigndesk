import type { ComponentType } from 'react';
import { Group, Panel, Separator } from 'react-resizable-panels';

import { QualityBadge } from '../components/QualityBadge';
import { type Slot, useMarket } from '../store/market';
import { FedPanel } from './FedPanel';
import { GenericPanel } from './GenericPanel';
import { GsecPanel } from './GsecPanel';
import { ImpactPanel } from './ImpactPanel';
import { LinkPanel } from './LinkPanel';
import { MpcPanel } from './MpcPanel';
import { PyPanel } from './PyPanel';
import { ReplayPanel } from './ReplayPanel';
import { SprdPanel } from './SprdPanel';
import { UstPanel } from './UstPanel';
import { WacrPanel } from './WacrPanel';

const PANELS: Record<string, ComponentType<{ slot: Slot }>> = {
  PY: PyPanel,
  FED: FedPanel,
  WACR: WacrPanel,
  UST: UstPanel,
  GSEC: GsecPanel,
  SPRD: SprdPanel,
  MPC: MpcPanel,
  LINK: LinkPanel,
  IMPACT: ImpactPanel,
  REPLAY: ReplayPanel,
};

const INDIA_PANELS = new Set(['WACR', 'CALL', 'LAF', 'NDTL', 'TAXCAL', 'GSEC', 'SPRD', 'MPC', 'LINK', 'IMPACT']);

export interface Quality {
  us: readonly string[];
  india: readonly string[];
}

function SlotView({ index, quality }: { index: number; quality: Quality }) {
  const slot = useMarket((s) => s.slots[index]);
  const focused = useMarket((s) => s.focused === index);
  const focus = useMarket((s) => s.focus);
  if (!slot) return null;
  const Body = PANELS[slot.panel] ?? GenericPanel;
  const labels = INDIA_PANELS.has(slot.panel) ? quality.india : quality.us;
  return (
    <section
      aria-label={`panel ${String(index + 1)}: ${slot.panel}`}
      onMouseDown={() => {
        focus(index);
      }}
      className={`flex h-full min-h-0 min-w-0 flex-col border ${focused ? 'border-term-amber' : 'border-term-line'}`}
    >
      <header className="flex items-center gap-2 border-b border-term-line bg-term-panel px-2 py-0.5 text-[11px]">
        <span className="text-term-muted">{index + 1}</span>
        <span className="font-semibold text-term-amber">{slot.panel}</span>
        {slot.panel !== 'HELP' && <QualityBadge labels={labels} />}
        <span className="truncate text-term-muted" title={slot.message}>
          {slot.message}
        </span>
      </header>
      <div className="min-h-0 min-w-0 flex-1 overflow-auto p-2">
        <Body slot={slot} />
      </div>
    </section>
  );
}

const handle = 'bg-term-line transition-colors hover:bg-term-amber';

/** Four resizable slots; each can show any function. Alt/Ctrl+1..4 or a click focuses one. */
export function PanelGrid({ quality }: { quality: Quality }) {
  return (
    <Group orientation="horizontal" className="h-full min-h-0">
      <Panel defaultSize="50%" minSize="20%">
        <Group orientation="vertical">
          <Panel defaultSize="55%" minSize="15%">
            <SlotView index={0} quality={quality} />
          </Panel>
          <Separator className={`h-1 ${handle}`} />
          <Panel minSize="15%">
            <SlotView index={2} quality={quality} />
          </Panel>
        </Group>
      </Panel>
      <Separator className={`w-1 ${handle}`} />
      <Panel minSize="20%">
        <Group orientation="vertical">
          <Panel defaultSize="55%" minSize="15%">
            <SlotView index={1} quality={quality} />
          </Panel>
          <Separator className={`h-1 ${handle}`} />
          <Panel minSize="15%">
            <SlotView index={3} quality={quality} />
          </Panel>
        </Group>
      </Panel>
    </Group>
  );
}
