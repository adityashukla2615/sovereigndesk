import type { CommandInfo } from '../market/types';
import type { Slot } from '../store/market';

function scalar(value: unknown): string | null {
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toPrecision(6);
  if (typeof value === 'string' || typeof value === 'boolean') return String(value);
  return null;
}

function isCommandList(value: unknown): value is CommandInfo[] {
  return Array.isArray(value) && value.every((c) => typeof c === 'object' && c !== null && 'code' in c);
}

/** A function without a panel of its own: its message and the simple values in its data. */
export function GenericPanel({ slot }: { slot: Slot }) {
  const reply = Object.values(slot.replies).at(-1);
  if (!reply) return <p className="p-2 text-xs text-term-muted">Type {slot.panel} to load it.</p>;
  const data = reply.data ?? {};
  const commands = data.commands;
  if (isCommandList(commands)) {
    return (
      <ul className="columns-2 gap-4 text-[11px] leading-5">
        {commands.map((c) => (
          <li key={c.code} className={c.available ? 'text-term-text' : 'text-term-muted'}>
            <span className="text-term-amber">{c.usage}</span> {c.summary}
            {!c.available && c.available_in ? ` · ${c.available_in}` : ''}
          </li>
        ))}
      </ul>
    );
  }
  const rows = Object.entries(data)
    .map(([k, v]) => [k, scalar(v)] as const)
    .filter((row): row is readonly [string, string] => row[1] !== null)
    .slice(0, 16);
  return (
    <div className="flex flex-col gap-2 text-xs">
      <p className="text-term-text">{reply.message}</p>
      {rows.length > 0 && (
        <table className="w-fit text-[11px]">
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <td className="pr-4 text-term-muted">{k}</td>
                <td className="text-term-text">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="text-[10px] text-term-muted">{slot.panel} has no chart of its own: its reply is shown as it came.</p>
    </div>
  );
}
