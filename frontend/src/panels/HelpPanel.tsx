import { type CommandInfo, isHelpPanel } from '../market/types';
import type { Slot } from '../store/market';
import { send } from '../ws/session';
import { TeachNote, Waiting } from './parts';

const GROUPS: [string, string][] = [
  ['US', 'US TREASURIES AND THE FED'],
  ['IN', 'INDIA MONEY MARKET'],
  ['X', 'CROSS-MARKET'],
  ['SYS', 'SYSTEM'],
];

const KEYS: [string, string][] = [
  ['/', 'focus the command bar'],
  ['↑ ↓ · Tab', 'pick or complete a code; walk the history'],
  ['Esc', 'leave the command bar, or go back to it from a panel'],
  ['Alt+1…4', 'focus a panel (Ctrl+1…4 where the browser allows)'],
  ['Alt+← → ↑ ↓', 'move to the neighbouring panel'],
  ['Alt+Enter', 'maximise the focused panel, or restore the grid'],
  ['F1', 'explain the focused panel'],
  ['Alt+T', 'teach mode on or off'],
];

/** Whether a function runs with no arguments (`CALL`, `HELP [code]`), so a click can run it. */
function runsBare(c: CommandInfo): boolean {
  const rest = c.usage.replace(/\|.*$/, '').trim().split(/\s+/).slice(1);
  return c.available && rest.every((token) => token.startsWith('['));
}

function Detail({ command }: { command: CommandInfo }) {
  return (
    <section aria-label={`help for ${command.code}`} className="border border-term-amber px-2 py-1 text-[11px]">
      <div className="text-term-amber">{command.usage}</div>
      <p className="text-term-text">{command.summary}</p>
      {!command.available && <p className="text-term-muted">Arrives in {command.available_in}.</p>}
      {runsBare(command) && (
        <button
          type="button"
          onClick={() => {
            send({ op: 'command', text: command.code });
          }}
          className="mt-1 rounded-sm border border-term-amber px-1 text-term-amber hover:bg-term-amber/20"
        >
          RUN {command.code}
        </button>
      )}
    </section>
  );
}

/** HELP: every function by market, the keys, and one function explained (`HELP SHOCK`). */
export function HelpPanel({ slot }: { slot: Slot }) {
  const data = slot.replies.HELP?.data;
  if (!isHelpPanel(data)) return <Waiting what="the function list (type HELP)" />;
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-2 overflow-auto">
      {data.command && <Detail command={data.command} />}
      <div className="columns-xs gap-4 text-[11px] leading-5">
        {GROUPS.map(([group, title]) => (
          <section key={group} aria-label={title} className="mb-2 break-inside-avoid">
            <h3 className="text-[10px] tracking-wider text-term-muted">{title}</h3>
            <ul>
              {data.commands
                .filter((c) => c.group === group)
                .map((c) => (
                  <li key={c.code} className={c.available ? 'text-term-text' : 'text-term-muted'}>
                    <button
                      type="button"
                      onClick={() => {
                        send({ op: 'command', text: `HELP ${c.code}` });
                      }}
                      className="text-left text-term-amber hover:underline"
                    >
                      {c.usage}
                    </button>{' '}
                    {c.summary}
                    {!c.available && c.available_in ? ` · ${c.available_in}` : ''}
                  </li>
                ))}
            </ul>
          </section>
        ))}
      </div>
      <section aria-label="keys" className="text-[11px]">
        <h3 className="text-[10px] tracking-wider text-term-muted">KEYS</h3>
        <table>
          <tbody>
            {KEYS.map(([key, what]) => (
              <tr key={key}>
                <td className="pr-3 whitespace-nowrap text-term-amber">{key}</td>
                <td className="text-term-text">{what}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <TeachNote code="HELP" />
    </div>
  );
}
