import type { LayoutRequest } from '../market/types';
import { useConnection } from '../store/connection';
import {
  DEFAULT_LAYOUT,
  type SavedLayout,
  deleteLayout,
  layoutOf,
  saveLayout,
  savedLayouts,
  useLayout,
} from '../store/layouts';
import { useMarket } from '../store/market';
import type { ClientMessage } from '../ws/protocol';

type Send = (message: ClientMessage) => void;

/** Show a layout: its panels and split at once, each filled as its command's reply arrives. */
export function restoreLayout(layout: SavedLayout, send: Send): void {
  useMarket.getState().setPanels(layout.panels, layout.commands);
  useLayout.getState().restoreSizes(layout.sizes);
  for (const text of new Set(layout.commands)) send({ op: 'command', text });
}

/** Carry out a LAYOUT reply: the backend checked the request, the layouts live in this browser. */
export function runLayout(request: LayoutRequest, send: Send): void {
  const note = useConnection.getState().note;
  const name = request.name ?? '';
  switch (request.action) {
    case 'list': {
      const names = Object.keys(savedLayouts()).sort();
      note(
        'LAYOUT',
        names.length > 0
          ? `Saved in this browser: ${names.join(', ')}. LAYOUT name restores one.`
          : 'No layouts saved yet: LAYOUT SAVE name keeps the four panels.',
        true,
      );
      return;
    }
    case 'save':
      if (!saveLayout(name, layoutOf(useMarket.getState().slots, useLayout.getState().sizes))) {
        note('LAYOUT', `Layout ${name} not saved: this browser's storage is unavailable`, false);
      }
      return;
    case 'load': {
      const saved = savedLayouts()[name];
      if (saved) restoreLayout(saved, send);
      else note('LAYOUT', `No layout ${name} saved in this browser. Type LAYOUT to list them.`, false);
      return;
    }
    case 'delete':
      if (!deleteLayout(name)) note('LAYOUT', `No layout ${name} saved in this browser`, false);
      return;
    case 'default':
      restoreLayout(DEFAULT_LAYOUT, send);
  }
}
