/**
 * The static web demo (`npm run build:demo`, published on GitHub Pages): the terminal plays back
 * replies and ticks recorded from the real simulator (`py tasks.py record-demo`) instead of
 * talking to a backend.
 */

export const STATIC_DEMO = import.meta.env.MODE === 'demo';

export const REPO_URL = 'https://github.com/adityashukla2615/sovereigndesk';

/** A recorded file of the demo, under the site's base path. */
export function demoUrl(file: string): string {
  return `${import.meta.env.BASE_URL}demo/${file}`;
}

/** The recorded answers that stand in for each REST endpoint. */
export const DEMO_FILES: Record<string, string> = {
  '/api/health': 'health.json',
  '/api/sim/status': 'status.json',
  '/api/commands': 'commands.json',
};
