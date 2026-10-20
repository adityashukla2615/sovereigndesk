import type { CommandInfo } from '../market/types';

const SUGGESTIONS = 8;

/** Functions whose code starts with what is typed, while the code is still being typed. */
export function suggest(commands: readonly CommandInfo[], text: string): CommandInfo[] {
  const typed = text.trimStart().toUpperCase();
  if (!typed || typed.includes(' ')) return [];
  return commands.filter((c) => c.code.startsWith(typed)).slice(0, SUGGESTIONS);
}
