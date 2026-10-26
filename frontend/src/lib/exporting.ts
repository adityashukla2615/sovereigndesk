/**
 * EXPORT: files the browser saves. Charts register how to draw themselves as an image, so EXPORT
 * PNG can stack a panel's charts into one picture under the panel's title.
 */

type Drawable = HTMLCanvasElement | HTMLImageElement;
type Render = () => Promise<Drawable>;

const renderers = new WeakMap<Element, Render>();

/** A chart's box and how to draw it (called by the chart components). */
export function registerChart(box: Element, render: Render): void {
  renderers.set(box, render);
}

export function unregisterChart(box: Element): void {
  renderers.delete(box);
}

/** An SVG data URL (ECharts' SVG renderer) as an image to draw. */
export function svgImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      resolve(image);
    };
    image.onerror = () => {
      reject(new Error('the chart image did not load'));
    };
    image.src = url;
  });
}

const SCALE = 2;
const TITLE = 22;
const GAP = 10;

/** The charts inside an element, stacked under a title, as a PNG; null when there are none. */
export async function chartsImage(
  root: Element,
  title: string,
  colours: { bg: string; text: string; muted: string },
): Promise<Blob | null> {
  const boxes = [...root.querySelectorAll('[data-chart]')].filter((box) => renderers.has(box));
  const parts: { label: string; image: Drawable; width: number; height: number }[] = [];
  for (const box of boxes) {
    const render = renderers.get(box);
    if (!render) continue;
    const rect = box.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) continue;
    parts.push({ label: box.getAttribute('aria-label') ?? '', image: await render(), width: rect.width, height: rect.height });
  }
  if (parts.length === 0) return null;
  const width = Math.max(...parts.map((p) => p.width)) + 2 * GAP;
  const height = TITLE + parts.reduce((sum, p) => sum + TITLE + p.height + GAP, GAP);
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(width * SCALE);
  canvas.height = Math.ceil(height * SCALE);
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.scale(SCALE, SCALE);
  ctx.fillStyle = colours.bg;
  ctx.fillRect(0, 0, width, height);
  ctx.font = '600 13px "IBM Plex Mono", monospace';
  ctx.fillStyle = colours.text;
  ctx.fillText(title, GAP, 16);
  let y = TITLE + GAP;
  ctx.font = '11px "IBM Plex Mono", monospace';
  for (const part of parts) {
    ctx.fillStyle = colours.muted;
    ctx.fillText(part.label, GAP, y + 12);
    ctx.drawImage(part.image, GAP, y + TITLE, part.width, part.height);
    y += TITLE + part.height + GAP;
  }
  return new Promise((resolve) => {
    canvas.toBlob(resolve, 'image/png');
  });
}

/** Save a file the way a download link would. */
export function download(name: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 1000);
}
