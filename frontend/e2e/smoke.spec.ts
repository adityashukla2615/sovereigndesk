/** Smoke test: the terminal on the real seed, every function's panel, the keys and layouts. */

import { readFile, stat } from 'node:fs/promises';

import { type Page, expect, test } from '@playwright/test';

/** Each function, and something its panel shows once its reply has arrived. */
const PANELS: [string, string, string][] = [
  ['UST', 'img', 'Treasury par curve, live against the official close'],
  ['FED', 'img', 'Reserve demand: EFFR − IORB against reserves'],
  ['DEBT', 'text', 'EXTRA COST, YEAR 1'],
  ['TIC', 'table', 'foreign holders'],
  ['CORR', 'text', 'EFFR − IORB'],
  ['CALL', 'table', 'money market rates'],
  ['WACR', 'img', 'Macro map: WACR against surplus'],
  ['LAF', 'table', 'operations outstanding'],
  ['NDTL', 'table', 'synthetic banks'],
  ['TAXCAL', 'table', 'tax windows ahead'],
  ['CCIL', 'img', 'How call money, TREPS and market repo trade and settle'],
  ['GSEC', 'text', 'NSS'],
  ['MPC', 'text', 'ORDERED LOGIT'],
  ['LINK', 'text', 'FPI'],
  ['HELP', 'region', 'INDIA MONEY MARKET'],
];

async function run(page: Page, text: string) {
  const bar = page.getByRole('combobox', { name: 'command' });
  await bar.fill(text);
  await bar.press('Enter');
}

const slot = (page: Page, n: number, code: string) => page.getByRole('region', { name: `panel ${String(n)}: ${code}` });

/** Uncaught errors and console errors on the page: a smoke test fails on any. */
let errors: string[] = [];

test.beforeEach(async ({ page }) => {
  errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  await page.goto('/');
  // The terminal opens on its four default functions, filled from the seed.
  await expect(slot(page, 1, 'PY')).toContainText('MOD DURATION');
  await expect(slot(page, 4, 'UST')).toContainText('2s10s');
});

test.afterEach(() => {
  expect(errors).toEqual([]);
});

test('every function answers on the real seed', async ({ page }) => {
  for (const [code, kind, name] of PANELS) {
    await run(page, code);
    // A function already on screen refreshes in its own slot; any other takes the focused one.
    const panel = page.getByRole('region', { name: new RegExp(`^panel \\d: ${code}$`) });
    if (kind === 'text') await expect(panel).toContainText(name);
    else await expect(panel.getByRole(kind as 'img' | 'table' | 'region', { name })).toBeVisible();
  }
  await run(page, 'REPLAY GILT2022');
  await expect(slot(page, 1, 'REPLAY').getByRole('table', { name: 'lambda specifications' })).toBeVisible();
  await run(page, 'IMPACT');
  await expect(slot(page, 1, 'IMPACT')).toContainText('ILLUSTRATIVE');
});

test('keys move between panels, maximise one and teach', async ({ page }) => {
  await page.keyboard.press('Alt+2');
  await expect(slot(page, 2, 'FED')).toBeFocused();
  await page.keyboard.press('Alt+ArrowDown');
  await expect(slot(page, 4, 'UST')).toBeFocused();
  await page.keyboard.press('Alt+Enter');
  await expect(page.getByRole('region', { name: /^panel / })).toHaveCount(1);
  await page.keyboard.press('Alt+Enter');
  await expect(page.getByRole('region', { name: /^panel / })).toHaveCount(4);
  await page.keyboard.press('Alt+t');
  await expect(slot(page, 4, 'UST').getByRole('complementary', { name: 'teach note for UST' })).toBeVisible();
  await page.keyboard.press('F1');
  await expect(slot(page, 4, 'HELP').getByRole('region', { name: 'help for UST' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('combobox', { name: 'command' })).toBeFocused();
});

test('a scenario saves and loads again, and a panel exports as CSV and PNG', async ({ page }) => {
  const log = page.getByRole('region', { name: 'event log' });
  await run(page, 'HIKE 25BP');
  await expect(log).toContainText('FOMC hike +25 bp');
  const hiked = /target range (\S+%–\S+%);/.exec((await log.textContent()) ?? '')?.[1];
  expect(hiked).toBeDefined();
  await run(page, 'SAVE E2E');
  await expect(log).toContainText('Scenario E2E saved');
  await run(page, 'CUT 50BP');
  await run(page, 'LOAD E2E');
  await expect(log).toContainText('Scenario E2E loaded: seed 7, 1 command(s) replayed');
  // The panels ask again: FED shows the run as saved, hike and all, not the later cut.
  await expect(slot(page, 2, 'FED')).toContainText(`Target range ${hiked ?? ''},`);

  const csv = page.waitForEvent('download');
  await run(page, 'EXPORT CSV');
  const table = await csv;
  expect(table.suggestedFilename()).toMatch(/^sovereigndesk-py-\d{12}\.csv$/);
  const text = await readFile(await table.path(), 'utf-8');
  expect(text.split('\r\n')[0]).toBe('shifts_bp,exact,duration_only,duration_convexity');
  const png = page.waitForEvent('download');
  await run(page, 'EXPORT PNG');
  const picture = await png;
  expect(picture.suggestedFilename()).toMatch(/^sovereigndesk-py-\d{12}\.png$/);
  expect((await stat(await picture.path())).size).toBeGreaterThan(10_000);
  await picture.saveAs(test.info().outputPath('panel.png')); // kept with the run, to look at
});

test('a saved layout comes back, and the terminal reopens as it was left', async ({ page }) => {
  await page.keyboard.press('Alt+3');
  await run(page, 'CCIL');
  await expect(slot(page, 3, 'CCIL')).toBeVisible();
  await run(page, 'LAYOUT SAVE E2E');
  await run(page, 'LAYOUT DEFAULT');
  await expect(slot(page, 3, 'WACR')).toContainText('WACR − REPO');
  await run(page, 'LAYOUT E2E');
  await expect(slot(page, 3, 'CCIL').getByRole('list', { name: 'sources' })).toBeVisible();
  await page.reload();
  await expect(slot(page, 3, 'CCIL').getByRole('list', { name: 'sources' })).toBeVisible();
  await run(page, 'LAYOUT');
  await expect(page.getByRole('region', { name: 'event log' })).toContainText('Saved in this browser: E2E');
});
