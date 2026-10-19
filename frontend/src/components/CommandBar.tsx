import { type KeyboardEvent, useEffect, useRef, useState } from 'react';

const HISTORY_LIMIT = 50;

function isEditable(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    (target instanceof HTMLElement && target.isContentEditable)
  );
}

/** Function-code input. `/` focuses it from anywhere, ↑/↓ walk history, Esc clears and blurs. */
export function CommandBar({ onSubmit }: { onSubmit: (text: string) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);

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

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    switch (event.key) {
      case 'Enter': {
        const text = value.trim();
        if (!text) return;
        onSubmit(text);
        setHistory((h) => [...h.filter((item) => item !== text), text].slice(-HISTORY_LIMIT));
        recall(null);
        break;
      }
      case 'ArrowUp':
        if (history.length === 0) return;
        event.preventDefault();
        recall(cursor === null ? history.length - 1 : Math.max(0, cursor - 1));
        break;
      case 'ArrowDown':
        if (cursor === null) return;
        event.preventDefault();
        recall(cursor + 1 < history.length ? cursor + 1 : null);
        break;
      case 'Escape':
        recall(null);
        inputRef.current?.blur();
        break;
    }
  };

  return (
    <label className="flex flex-1 items-center gap-2 rounded-sm border border-term-line bg-term-panel px-2 py-1 focus-within:border-term-amber">
      <span aria-hidden="true" className="text-term-amber">
        &gt;
      </span>
      <input
        ref={inputRef}
        aria-label="command"
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
        }}
        onKeyDown={onKeyDown}
        spellCheck={false}
        autoComplete="off"
        placeholder="Type a function code, e.g. QT 95B   ( / to focus )"
        className="w-full bg-transparent text-sm text-term-text outline-none placeholder:text-term-muted"
      />
    </label>
  );
}
