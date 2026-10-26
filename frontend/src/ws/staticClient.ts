import { demoUrl } from '../lib/staticDemo';
import type { ConnectionStatus } from './client';
import type { ClientMessage, Envelope } from './protocol';

/** One recorded moment of both markets (the payloads of `us.tick` and `in.tick`). */
export interface Frame {
  us: unknown;
  india: unknown;
}

export type RecordedReply = Record<string, unknown>;

export interface Recorded {
  reply: RecordedReply;
  events: unknown[];
}

/** A command that moved the markets: its tape, and the panels it changed as they then read. */
export interface RecordedAction extends Recorded {
  tape: Frame[];
  after: Record<string, RecordedReply>;
}

/** What `scripts/record_demo.py` writes to `demo/session.json`. */
export interface DemoSession {
  recorded: string;
  start: string;
  history: unknown[];
  baseline: Frame[];
  replies: Record<string, Recorded>;
  actions: Record<string, RecordedAction>;
  reset: Recorded;
}

export interface StaticClientOptions {
  onMessage: (message: Envelope) => void;
  onStatus: (status: ConnectionStatus) => void;
  /** Injectable for tests. */
  load?: () => Promise<DemoSession>;
  frameMs?: number;
}

const NAME = /^[A-Z0-9][A-Z0-9_-]{0,23}$/;
const LIVE_ONLY = 'needs the live terminal: run SovereignDesk locally (see the README)';

async function fetchJson<T>(file: string): Promise<T> {
  const response = await fetch(demoUrl(file));
  if (!response.ok) throw new Error(`demo ${file}: HTTP ${String(response.status)}`);
  return (await response.json()) as T;
}

/** The recording, kept in files under 1 MB: the replies, the opening tape, the commands that
 * moved the markets and their tapes. */
async function fetchSession(): Promise<DemoSession> {
  const [session, baseline, actions, tapes] = await Promise.all([
    fetchJson<Omit<DemoSession, 'baseline' | 'actions'>>('session.json'),
    fetchJson<Frame[]>('baseline.json'),
    fetchJson<Record<string, Omit<RecordedAction, 'tape'>>>('actions.json'),
    fetchJson<Record<string, Frame[]>>('tapes.json'),
  ]);
  const joined = Object.fromEntries(
    Object.entries(actions).map(([text, action]) => [text, { ...action, tape: tapes[text] ?? [] }]),
  );
  return { ...session, baseline, actions: joined };
}

function reply(code: string, ok: boolean, message: string, data: unknown = null): RecordedReply {
  return { ok, code, message, panel: null, data };
}

/** LAYOUT, as the backend checks it (app.commands.system.layout); the browser carries it out. */
function layout(args: string[]): RecordedReply {
  let action: string;
  let name: string | null = null;
  if (args.length === 0) action = 'list';
  else if (args.length === 1 && args[0] === 'DEFAULT') action = 'default';
  else if (args.length === 2 && (args[0] === 'SAVE' || args[0] === 'DELETE')) {
    action = args[0].toLowerCase();
    name = args[1] ?? null;
  } else if (args.length === 1) {
    action = 'load';
    name = args[0] ?? null;
  } else {
    return reply('LAYOUT', false, 'Usage: LAYOUT, LAYOUT SAVE name, LAYOUT name, LAYOUT DELETE name or LAYOUT DEFAULT');
  }
  if (name !== null && (['SAVE', 'DELETE', 'DEFAULT'].includes(name) || !NAME.test(name))) {
    return reply('LAYOUT', false, 'A layout name is up to 24 letters, digits, - or _, e.g. RATES');
  }
  const messages: Record<string, string> = {
    list: 'Layouts saved in this browser',
    default: 'Default layout: PY, FED, WACR and UST',
    save: `Layout ${name ?? ''}: the four panels saved in this browser`,
    load: `Layout ${name ?? ''}: restoring its panels`,
    delete: `Layout ${name ?? ''} deleted from this browser`,
  };
  return reply('LAYOUT', true, messages[action] ?? '', { layout: { action, name } });
}

/**
 * The terminal's transport in the static demo: it answers commands from the recording and plays
 * the recorded ticks in a loop. A command that moved the markets switches to its own tape, and the
 * panels it changed then show the replies recorded after it; RESET goes back to the opening.
 */
export class StaticClient {
  private readonly options: StaticClientOptions;
  private session: DemoSession | null = null;
  private readonly queue: ClientMessage[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;
  private stopped = true;
  private paused = false;
  private seq = 0;
  private tape: Frame[] = [];
  private frame = 0;
  private action: string | null = null;

  constructor(options: StaticClientOptions) {
    this.options = options;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.options.onStatus('connecting');
    (this.options.load ?? fetchSession)()
      .then((session) => {
        if (this.stopped) return;
        this.session = session;
        this.tape = session.baseline;
        this.options.onStatus('open');
        this.emit('events', session.history);
        this.play();
        for (const message of this.queue.splice(0)) this.handle(message);
      })
      .catch(() => {
        this.options.onStatus('closed');
      });
  }

  stop(): void {
    this.stopped = true;
    this.halt();
    this.options.onStatus('closed');
  }

  send(message: ClientMessage): void {
    if (this.session) this.handle(message);
    else this.queue.push(message);
  }

  private play(): void {
    this.halt();
    this.tick();
    this.timer = setInterval(() => {
      this.tick();
    }, this.options.frameMs ?? 1000);
  }

  private halt(): void {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
  }

  private tick(): void {
    const frame = this.tape[this.frame % Math.max(this.tape.length, 1)];
    this.frame += 1;
    if (!frame) return;
    this.emit('us.tick', frame.us);
    this.emit('in.tick', frame.india);
  }

  private emit(topic: string, data: unknown): void {
    this.seq += 1;
    this.options.onMessage({ topic, ts: new Date().toISOString(), seq: this.seq, data });
  }

  private switchTo(tape: Frame[], action: string | null): void {
    this.tape = tape;
    this.frame = 0;
    this.action = action;
    if (!this.paused) this.play();
  }

  private handle(message: ClientMessage): void {
    const session = this.session;
    if (message.op !== 'command' || !session) return;
    const text = message.text.trim().toUpperCase().split(/\s+/).join(' ');
    const [code = '', ...args] = text.split(' ');
    let answer: RecordedReply;
    let events: unknown[] = [];
    const action = session.actions[text];
    if (code === 'LAYOUT') answer = layout(args);
    else if (code === 'EXPORT') {
      const format = args.length === 1 ? args[0]?.toLowerCase() : undefined;
      answer =
        format === 'csv' || format === 'png'
          ? reply('EXPORT', true, `Exporting the focused panel as ${format.toUpperCase()}`, { export: { format } })
          : reply('EXPORT', false, 'Usage: EXPORT CSV (the panel’s data) or EXPORT PNG (its charts)');
    } else if (code === 'SAVE' || code === 'LOAD' || code === 'SPEED') {
      answer = reply(code, false, `${code} ${LIVE_ONLY}`);
    } else if (code === 'PAUSE' || code === 'RESUME') {
      this.paused = code === 'PAUSE';
      if (this.paused) this.halt();
      else this.play();
      answer = reply(code, true, this.paused ? 'Playback paused' : 'Playback resumed');
    } else if (text === 'RESET') {
      answer = session.reset.reply;
      events = session.reset.events;
      this.switchTo(session.baseline, null);
    } else if (action) {
      answer = action.reply;
      events = action.events;
      this.switchTo(action.tape, text);
    } else {
      const after = this.action ? session.actions[this.action]?.after[text] : undefined;
      const view = session.replies[text];
      if (after) answer = after;
      else if (view) {
        answer = view.reply;
        events = view.events;
      } else answer = this.missing(text, code);
    }
    for (const event of events) this.emit('events', event);
    this.emit('command', { ...answer, command: text });
  }

  private missing(text: string, code: string): RecordedReply {
    const session = this.session;
    const recorded = session ? [...Object.keys(session.replies), ...Object.keys(session.actions)] : [];
    const siblings = recorded.filter((k) => k === code || k.startsWith(`${code} `)).slice(0, 5);
    if (siblings.length === 0) return reply(code, false, `Unknown function ${code} in this demo. Type HELP.`);
    return reply(
      code,
      false,
      `${text} was not recorded for this static demo. Try ${siblings.join(', ')}; every other variant ${LIVE_ONLY}`,
    );
  }
}
