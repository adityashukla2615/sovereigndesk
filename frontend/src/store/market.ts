import { create } from 'zustand';

import type { CommandReply, InTick, UsTick } from '../market/types';

/** What each of the four slots shows when the terminal opens, and the commands that fill them. */
export const DEFAULT_PANELS = ['PY', 'FED', 'WACR', 'UST'] as const;
export const STARTUP_COMMANDS = ['PY 10Y', 'FED', 'WACR', 'UST'] as const;
export const SLOT_COUNT = 4;

export interface Slot {
  panel: string;
  /** The command that fills this slot (`PY 10Y`): what a layout runs to show it again. */
  command: string;
  /** The latest successful reply for this panel, by command code (FED and QT both feed FED). */
  replies: Record<string, CommandReply>;
  message: string;
}

interface MarketState {
  us: UsTick | null;
  india: InTick | null;
  /** The previous ticks, for the ticker's up/down colours. */
  usBefore: UsTick | null;
  indiaBefore: InTick | null;
  slots: Slot[];
  focused: number;
  teach: boolean;
  setUs: (tick: UsTick) => void;
  setIndia: (tick: InTick) => void;
  applyReply: (reply: CommandReply) => void;
  /** Show these functions in the four slots, empty until their commands' replies arrive. */
  setPanels: (panels: readonly string[], commands?: readonly string[]) => void;
  focus: (index: number) => void;
  toggleTeach: () => void;
}

export function initialSlots(): Slot[] {
  return DEFAULT_PANELS.map((panel, i) => ({ panel, command: STARTUP_COMMANDS[i] ?? panel, replies: {}, message: '' }));
}

/**
 * Where a reply goes: a slot already showing its panel is refreshed. A function asked for by
 * name (PY, WACR, …) otherwise takes the focused slot; an action whose story is another panel's
 * (VRR → LAF, HIKE → FED) only refreshes that panel if it is open. Failures reach the log only.
 */
export function routeReply(slots: Slot[], focused: number, reply: CommandReply): Slot[] {
  if (!reply.ok || reply.panel === null || reply.panel === 'TEACH') return slots;
  const panel = reply.panel;
  const index = slots.findIndex((slot) => slot.panel === panel);
  if (index < 0 && reply.code !== panel) return slots;
  const target = index >= 0 ? index : focused;
  return slots.map((slot, i) => {
    if (i !== target) return slot;
    const replies = slot.panel === panel ? { ...slot.replies } : {};
    replies[reply.code] = reply;
    // Asked for by name, the reply's command fills the slot; an action (QT on FED) leaves it.
    const command = reply.code === panel ? (reply.command ?? panel) : slot.panel === panel ? slot.command : panel;
    return { panel, command, replies, message: reply.message };
  });
}

export const useMarket = create<MarketState>()((set) => ({
  us: null,
  india: null,
  usBefore: null,
  indiaBefore: null,
  slots: initialSlots(),
  focused: 0,
  teach: false,
  setUs: (tick) => {
    set((state) => ({ us: tick, usBefore: state.us }));
  },
  setIndia: (tick) => {
    set((state) => ({ india: tick, indiaBefore: state.india }));
  },
  applyReply: (reply) => {
    set((state) => ({
      slots: routeReply(state.slots, state.focused, reply),
      teach: reply.ok && reply.code === 'TEACH' ? !state.teach : state.teach,
    }));
  },
  setPanels: (panels, commands = panels) => {
    set({
      slots: panels
        .slice(0, SLOT_COUNT)
        .map((panel, i) => ({ panel, command: commands[i] ?? panel, replies: {}, message: '' })),
    });
  },
  focus: (index) => {
    if (index >= 0 && index < SLOT_COUNT) set({ focused: index });
  },
  toggleTeach: () => {
    set((state) => ({ teach: !state.teach }));
  },
}));
