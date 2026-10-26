import { panelTable, toCsv } from '../lib/csv';
import { chartsImage, download } from '../lib/exporting';
import { palette } from '../lib/palette';
import { useConnection } from '../store/connection';
import { useMarket } from '../store/market';

function stamp(): string {
  const time = useMarket.getState().us?.sim_time ?? useMarket.getState().india?.sim_time ?? new Date().toISOString();
  return time.slice(0, 16).replace(/[-:T]/g, '');
}

function fileName(panel: string, part: string, ext: string): string {
  const what = part ? `-${part.replace(/[^A-Za-z0-9]+/g, '-')}` : '';
  return `sovereigndesk-${panel.toLowerCase()}${what}-${stamp()}.${ext}`;
}

/** Carry out EXPORT CSV|PNG on the focused panel: the backend checked it, the browser saves. */
export async function runExport(format: 'csv' | 'png'): Promise<void> {
  const { slots, focused, us, india } = useMarket.getState();
  const note = useConnection.getState().note;
  const slot = slots[focused];
  if (!slot) return;
  if (format === 'csv') {
    const table = panelTable(slot, { usCurve: us?.curve ?? null, gsec: india?.gsec?.points ?? null });
    if (!table || table.rows.length === 0) {
      note('EXPORT', `${slot.panel} has no data to export yet: run it first`, false);
      return;
    }
    const name = fileName(slot.panel, table.name, 'csv');
    download(name, new Blob([toCsv(table)], { type: 'text/csv;charset=utf-8' }));
    note('EXPORT', `Saved ${name}: ${String(table.rows.length)} rows × ${String(table.columns.length)} columns`, true);
    return;
  }
  const section = document.querySelector(`[data-slot="${String(focused)}"]`);
  const p = palette();
  const title = `SOVEREIGNDESK · ${slot.panel} · ${slot.message}`;
  const image = section ? await chartsImage(section, title.slice(0, 120), { bg: p.bg, text: p.amber, muted: p.muted }) : null;
  if (!image) {
    note('EXPORT', `${slot.panel} shows no chart to export: EXPORT CSV saves its data`, false);
    return;
  }
  const name = fileName(slot.panel, '', 'png');
  download(name, image);
  note('EXPORT', `Saved ${name}`, true);
}
