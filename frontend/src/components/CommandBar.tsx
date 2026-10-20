import { type KeyboardEvent, useEffect, useRef, useState } from 'react';

import { suggest } from '../lib/suggest';
import type { CommandInfo } from '../market/types';

const HISTORY_LIMIT = 50;

function isEditable(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    (target instanceof HTMLElement && target.isContentEditable)
  );
}

/**
 * Function-code input. `/` focuses it from anywhere; while typing a code, ↑/↓ pick a suggestion
 * and Tab completes it; otherwise ↑/↓ walk the history. Esc clears and blurs.
 */
export function CommandBar({
  onSubmit,
  commands = [],
}: {
  onSubmit: (text: string) => void;
  commands?: readonly CommandInfo[];
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [pick, setPick] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const options = open ? suggest(commands, value) : [];

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === '/' && !isEditable(event.target)) {
        event.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  }, []);

  const recall = (index: number | null) => {
    setCursor(index);
    setValue(index === null ? '' : (history[index] ?? ''));
  };

  const complete = (option: CommandInfo | undefined) => {
    if (!option) return;
    setValue(`${option.code} `);
    setPick(null);
  };

  const submit = (text: string) => {
    if (!text) return;
    onSubmit(text);
    setHistory((h) => [...h.filter((item) => item !== text), text].slice(-HISTORY_LIMIT));
    setPick(null);
    recall(null);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    const picking = options.length > 0;
    switch (event.key) {
      case 'Enter': {
        const chosen = pick === null ? undefined : options[pick];
        submit(chosen ? chosen.code : value.trim());
        break;
      }
      case 'Tab':
        if (!picking) return;
        event.preventDefault();
        complete(options[pick ?? 0]);
        break;
      case 'ArrowUp':
        event.preventDefault();
        if (picking) {
          setPick((p) => (p === null ? options.length - 1 : Math.max(0, p - 1)));
        } else if (history.length > 0) {
          recall(cursor === null ? history.length - 1 : Math.max(0, cursor - 1));
        }
        break;
      case 'ArrowDown':
        event.preventDefault();
        if (picking) {
          setPick((p) => (p === null ? 0 : Math.min(options.length - 1, p + 1)));
        } else if (cursor !== null) {
          recall(cursor + 1 < history.length ? cursor + 1 : null);
        }
        break;
      case 'Escape':
        setPick(null);
        recall(null);
        inputRef.current?.blur();
        break;
    }
  };

  return (
    <div className="relative flex-1">
      <label className="flex items-center gap-2 rounded-sm border border-term-line bg-term-panel px-2 py-1 focus-within:border-term-amber">
        <span aria-hidden="true" className="text-term-amber">
          &gt;
        </span>
        <input
          ref={inputRef}
          aria-label="command"
          role="combobox"
          aria-expanded={options.length > 0}
          aria-controls="command-suggestions"
          aria-autocomplete="list"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setPick(null);
            setOpen(true);
          }}
          onFocus={() => {
            setOpen(true);
          }}
          onBlur={() => {
            setOpen(false);
          }}
          onKeyDown={onKeyDown}
          spellCheck={false}
          autoComplete="off"
          placeholder="Type a function code, e.g. QT 95B   ( / to focus · TEACH for notes )"
          className="w-full bg-transparent text-sm text-term-text outline-none placeholder:text-term-muted"
        />
      </label>
      {options.length > 0 && (
        <ul
          id="command-suggestions"
          role="listbox"
          className="absolute top-full right-0 left-0 z-20 mt-0.5 border border-term-line bg-term-panel text-xs shadow-lg"
        >
          {options.map((c, i) => (
            <li
              key={c.code}
              role="option"
              aria-selected={pick === i}
              onMouseDown={(event) => {
                event.preventDefault();
                complete(c);
              }}
              className={`flex gap-3 px-2 py-0.5 ${pick === i ? 'bg-term-line' : ''} ${c.available ? 'text-term-text' : 'text-term-muted'}`}
            >
              <span className="w-40 shrink-0 text-term-amber">{c.usage}</span>
              <span className="truncate">{c.summary}</span>
              {!c.available && <span className="ml-auto shrink-0">{c.available_in}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
