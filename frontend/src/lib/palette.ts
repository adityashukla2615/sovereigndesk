/**
 * Chart colours. Charts draw on SVG and need concrete values, so they read the terminal's CSS
 * tokens (index.css); the fallbacks repeat those tokens for environments without the stylesheet.
 */

const FALLBACK = {
  bg: '#000000',
  panel: '#0b0b0b',
  line: '#2a2a2a',
  amber: '#ffb000',
  text: '#e8e6e3',
  muted: '#7d7d7d',
  up: '#2fd16b',
  down: '#ff4d4d',
  accent: '#4fb3ff',
} as const;

export type PaletteKey = keyof typeof FALLBACK;
export type Palette = Record<PaletteKey, string>;

export function palette(): Palette {
  const style =
    typeof document === 'undefined' ? null : getComputedStyle(document.documentElement);
  const read = (key: PaletteKey): string =>
    style?.getPropertyValue(`--color-term-${key}`).trim() ?? '';
  return {
    bg: read('bg') || FALLBACK.bg,
    panel: read('panel') || FALLBACK.panel,
    line: read('line') || FALLBACK.line,
    amber: read('amber') || FALLBACK.amber,
    text: read('text') || FALLBACK.text,
    muted: read('muted') || FALLBACK.muted,
    up: read('up') || FALLBACK.up,
    down: read('down') || FALLBACK.down,
    accent: read('accent') || FALLBACK.accent,
  };
}
