import type { CommandInfo } from '../market/types';

const SUGGESTIONS = 8;

/** Functions whose code starts with what is typed, while the code is still being typed. */
export function suggest(commands: readonly CommandInfo[], text: string): CommandInfo[] {
  const typed = text.trimStart().toUpperCase();
  if (!typed || typed.includes(' ')) return [];
  return commands.filter((c) => c.code.startsWith(typed)).slice(0, SUGGESTIONS);
}

/** Whether a function's usage asks for something after its code (HIKE 25BP, QT 95B | QT OFF)
 * rather than running alone or with options in brackets (UST, PY [tenor], LAYOUT [SAVE|…]). */
export function needsArguments(command: CommandInfo): boolean {
  const first = (command.usage.split('|')[0] ?? '').trim().split(/\s+/)[1];
  return first !== undefined && !first.startsWith('[');
}
