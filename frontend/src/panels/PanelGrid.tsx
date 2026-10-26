import type { ComponentType } from 'react';
import { Group, Panel, Separator } from 'react-resizable-panels';

import { QualityBadge } from '../components/QualityBadge';
import { useLayout } from '../store/layouts';
import { type Slot, useMarket } from '../store/market';
import { CallPanel } from './CallPanel';
import { CcilPanel } from './CcilPanel';
import { CorrPanel } from './CorrPanel';
import { DebtPanel } from './DebtPanel';
import { FedPanel } from './FedPanel';
import { GenericPanel } from './GenericPanel';
import { GsecPanel } from './GsecPanel';
import { HelpPanel } from './HelpPanel';
import { ImpactPanel } from './ImpactPanel';
import { LafPanel } from './LafPanel';
import { LinkPanel } from './LinkPanel';
import { MpcPanel } from './MpcPanel';
import { NdtlPanel } from './NdtlPanel';
import { PyPanel } from './PyPanel';
import { ReplayPanel } from './ReplayPanel';
import { SprdPanel } from './SprdPanel';
import { TaxcalPanel } from './TaxcalPanel';
import { TicPanel } from './TicPanel';
import { UstPanel } from './UstPanel';
import { WacrPanel } from './WacrPanel';

export const PANELS: Record<string, ComponentType<{ slot: Slot }>> = {
  PY: PyPanel,
  UST: UstPanel,
  FED: FedPanel,
  DEBT: DebtPanel,
  TIC: TicPanel,
  CORR: CorrPanel,
  CALL: CallPanel,
  WACR: WacrPanel,
  LAF: LafPanel,
  NDTL: NdtlPanel,
  TAXCAL: TaxcalPanel,
  CCIL: CcilPanel,
  GSEC: GsecPanel,
  SPRD: SprdPanel,
  MPC: MpcPanel,
  LINK: LinkPanel,
  IMPACT: ImpactPanel,
  REPLAY: ReplayPanel,
  HELP: HelpPanel,
};

const INDIA_PANELS = new Set([
  'WACR',
  'CALL',
  'LAF',
  'NDTL',
  'TAXCAL',
  'CCIL',
  'GSEC',
  'SPRD',
  'MPC',
  'LINK',
  'IMPACT',
]);

export interface Quality {
  us: readonly string[];
  india: readonly string[];
}

function SlotView({ index, quality }: { index: number; quality: Quality }) {
  const slot = useMarket((s) => s.slots[index]);
  const focused = useMarket((s) => s.focused === index);
  const focus = useMarket((s) => s.focus);
  const maximized = useLayout((s) => s.maximized === index);
  if (!slot) return null;
  const Body = PANELS[slot.panel] ?? GenericPanel;
  const labels = INDIA_PANELS.has(slot.panel) ? quality.india : quality.us;
  return (
    <section
      aria-label={`panel ${String(index + 1)}: ${slot.panel}`}
      data-slot={index}
      tabIndex={0}
      onMouseDown={() => {
        focus(index);
      }}
      onFocus={() => {
        focus(index);
      }}
      className={`flex h-full min-h-0 min-w-0 flex-col border outline-none ${focused ? 'border-term-amber' : 'border-term-line'}`}
    >
      <header className="flex items-center gap-2 border-b border-term-line bg-term-panel px-2 py-0.5 text-[11px]">
        <span className="text-term-muted">{index + 1}</span>
        <span className="font-semibold text-term-amber">{slot.panel}</span>
        {slot.panel !== 'HELP' && <QualityBadge labels={labels} />}
        <span className="truncate text-term-muted" title={slot.message}>
          {slot.message}
        </span>
        {maximized && <span className="ml-auto shrink-0 text-term-muted">MAX · Alt+Enter</span>}
      </header>
      <div className="min-h-0 min-w-0 flex-1 overflow-auto p-2">
        <Body slot={slot} />
      </div>
    </section>
  );
}

const handle = 'bg-term-line transition-colors hover:bg-term-amber';

/** Four resizable slots; each can show any function. Alt/Ctrl+1..4, Alt+arrows or a click focus
 * one, and Alt+Enter shows it alone. The split is kept with saved layouts. */
export function PanelGrid({ quality }: { quality: Quality }) {
  const maximized = useLayout((s) => s.maximized);
  const version = useLayout((s) => s.version);
  const setSizes = useLayout((s) => s.setSizes);
  if (maximized !== null) return <SlotView index={maximized} quality={quality} />;
  // The split is read when the grid mounts: a restored layout remounts it (``version``).
  const sizes = useLayout.getState().sizes;
  return (
    <Group
      key={version}
      id="columns"
      orientation="horizontal"
      className="h-full min-h-0"
      defaultLayout={sizes.columns}
      onLayoutChanged={(layout) => {
        setSizes('columns', layout);
      }}
    >
      <Panel id="left" defaultSize="50%" minSize="20%">
        <Group
          id="left-rows"
          orientation="vertical"
          defaultLayout={sizes['left-rows']}
          onLayoutChanged={(layout) => {
            setSizes('left-rows', layout);
          }}
        >
          <Panel id="slot-1" defaultSize="55%" minSize="15%">
            <SlotView index={0} quality={quality} />
          </Panel>
          <Separator className={`h-1 ${handle}`} />
          <Panel id="slot-3" minSize="15%">
            <SlotView index={2} quality={quality} />
          </Panel>
        </Group>
      </Panel>
      <Separator className={`w-1 ${handle}`} />
      <Panel id="right" minSize="20%">
        <Group
          id="right-rows"
          orientation="vertical"
          defaultLayout={sizes['right-rows']}
          onLayoutChanged={(layout) => {
            setSizes('right-rows', layout);
          }}
        >
          <Panel id="slot-2" defaultSize="55%" minSize="15%">
            <SlotView index={1} quality={quality} />
          </Panel>
          <Separator className={`h-1 ${handle}`} />
          <Panel id="slot-4" minSize="15%">
            <SlotView index={3} quality={quality} />
          </Panel>
        </Group>
      </Panel>
    </Group>
  );
}
