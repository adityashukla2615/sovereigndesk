/**
 * Layouts: which function each of the four slots shows, the command that filled it, and how the
 * grid is split. Saved ones and the last one live in this browser's localStorage (a missing or
 * blocked storage only means nothing is remembered).
 */

import { create } from 'zustand';

import type { Slot } from './market';
import { DEFAULT_PANELS, SLOT_COUNT, STARTUP_COMMANDS } from './market';

/** Group id → panel id → share of the group (per cent). */
export type Sizes = Record<string, Record<string, number>>;

export interface SavedLayout {
  panels: string[];
  commands: string[];
  sizes: Sizes;
}

export const DEFAULT_LAYOUT: SavedLayout = {
  panels: [...DEFAULT_PANELS],
  commands: [...STARTUP_COMMANDS],
  sizes: {},
};

const SAVED_KEY = 'sovereigndesk.layouts';
const LAST_KEY = 'sovereigndesk.layout.last';

function read(key: string): unknown {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? null : (JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

function write(key: string, value: unknown): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

function isStrings(value: unknown): value is string[] {
  return Array.isArray(value) && value.length === SLOT_COUNT && value.every((v) => typeof v === 'string');
}

function isSizes(value: unknown): value is Sizes {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  return Object.values(value).every(
    (group) =>
      typeof group === 'object' &&
      group !== null &&
      Object.values(group as Record<string, unknown>).every((v) => typeof v === 'number' && Number.isFinite(v)),
  );
}

export function isSavedLayout(value: unknown): value is SavedLayout {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return isStrings(v.panels) && isStrings(v.commands) && isSizes(v.sizes);
}

export function savedLayouts(): Record<string, SavedLayout> {
  const value = read(SAVED_KEY);
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, SavedLayout] => isSavedLayout(entry[1])));
}

export function saveLayout(name: string, layout: SavedLayout): boolean {
  return write(SAVED_KEY, { ...savedLayouts(), [name]: layout });
}

/** Whether there was a layout of that name to delete. */
export function deleteLayout(name: string): boolean {
  const saved = savedLayouts();
  if (!(name in saved)) return false;
  return write(SAVED_KEY, Object.fromEntries(Object.entries(saved).filter(([key]) => key !== name)));
}

export function lastLayout(): SavedLayout | null {
  const value = read(LAST_KEY);
  return isSavedLayout(value) ? value : null;
}

let remembered = '';

/** Keep the current layout as the one to reopen with (only writes when it changed). */
export function rememberLayout(layout: SavedLayout): void {
  const text = JSON.stringify(layout);
  if (text === remembered) return;
  remembered = text;
  write(LAST_KEY, layout);
}

/** The layout the slots show now: each slot's panel and the command that fills it. */
export function layoutOf(slots: readonly Slot[], sizes: Sizes): SavedLayout {
  return { panels: slots.map((s) => s.panel), commands: slots.map((s) => s.command), sizes };
}

interface LayoutState {
  sizes: Sizes;
  /** Bumped when a layout is restored, so the grid remounts with its sizes. */
  version: number;
  /** The slot shown alone, or null for the grid. */
  maximized: number | null;
  setSizes: (group: string, layout: Record<string, number>) => void;
  restoreSizes: (sizes: Sizes) => void;
  toggleMaximized: (index: number) => void;
}

export const useLayout = create<LayoutState>()((set) => ({
  sizes: {},
  version: 0,
  maximized: null,
  setSizes: (group, layout) => {
    set((state) => ({ sizes: { ...state.sizes, [group]: { ...layout } } }));
  },
  restoreSizes: (sizes) => {
    set((state) => ({ sizes, version: state.version + 1, maximized: null }));
  },
  toggleMaximized: (index) => {
    set((state) => ({ maximized: state.maximized === index ? null : index }));
  },
}));
