import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import {
  Activity,
  CheckCircle,
  Clock3,
  Gauge,
  HeartPulse,
  Layers,
  LibraryBig,
  MessageSquare,
  MessagesSquare,
  Moon,
  Network,
  Plus,
  Search,
  Sparkles,
  Sun,
  Users,
  X,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import { api, type SessionSummary } from '../api/client';

/* ─────────────────────────────────────────────────────────
 * COMMAND PALETTE — ⌘K / Ctrl+K, or the topbar title
 *
 * One live-filtered list over things that exist: every view,
 * the workspace's real chat history, and a few actions. ↑↓ to
 * move, Enter to go, Esc to close. A single highlight glides to
 * the active row. With no query it shows actions and views, and
 * the most recent chats.
 * ───────────────────────────────────────────────────────── */

type Item = {
  id: string;
  group: 'Actions' | 'Views' | 'Chats';
  label: string;
  hint?: string;
  icon: ReactNode;
  keywords?: string;
  run: () => void;
};

const VIEWS: { label: string; icon: ReactNode; keywords?: string }[] = [
  { label: 'Chat', icon: <MessageSquare size={15} /> },
  { label: 'Knowledge Bases', icon: <LibraryBig size={15} />, keywords: 'documents files upload' },
  { label: 'Memory Graph', icon: <Network size={15} />, keywords: 'entities edges' },
  { label: 'Session Working Set', icon: <Layers size={15} /> },
  { label: 'Memory Pipeline', icon: <Activity size={15} />, keywords: 'slow path consolidation journal' },
  { label: 'Memory Health', icon: <HeartPulse size={15} />, keywords: 'sleep retention' },
  { label: 'Retrieval Trace', icon: <Search size={15} /> },
  { label: 'Reflections', icon: <Sparkles size={15} /> },
  { label: 'Communities', icon: <Users size={15} /> },
  { label: 'Foresight', icon: <Clock3 size={15} />, keywords: 'timeline reminders' },
  { label: 'Evaluation', icon: <CheckCircle size={15} />, keywords: 'benchmarks results' },
];

const RECENT_CHATS_WHEN_EMPTY = 5;

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { view, setView, setActiveThread, setSessionId, theme, toggleTheme, authUser } = useApp();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [box, setBox] = useState<{ top: number; height: number } | null>(null);

  // fresh history each time it opens
  useEffect(() => {
    if (!open) return;
    setQuery('');
    setActive(0);
    let live = true;
    api
      .sessions({ limit: 50 })
      .then((res) => live && setSessions(res.sessions))
      .catch(() => live && setSessions([]));
    inputRef.current?.focus(); // the input is mounted by the time this effect runs
    return () => {
      live = false;
    };
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const go = (label: string) => () => setView(label);
    const actions: Item[] = [
      {
        id: 'new-chat',
        group: 'Actions',
        label: 'New chat',
        icon: <Plus size={15} />,
        keywords: 'start conversation',
        run: () => {
          setView('Chat');
          setActiveThread('new');
          setSessionId(null);
        },
      },
      {
        id: 'theme',
        group: 'Actions',
        label: theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme',
        icon: theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />,
        keywords: 'theme appearance mode',
        run: toggleTheme,
      },
    ];
    const views: Item[] = [
      ...VIEWS,
      ...(authUser?.isPlatformAdmin ? [{ label: 'Administration', icon: <Gauge size={15} />, keywords: 'admin platform provider' }] : []),
    ].map((v) => ({
      id: `view-${v.label}`,
      group: 'Views' as const,
      label: v.label,
      hint: v.label === view ? 'Current' : undefined,
      icon: v.icon,
      keywords: v.keywords,
      run: go(v.label),
    }));
    const chats: Item[] = (sessions ?? []).map((s) => ({
      id: `chat-${s.session_id}`,
      group: 'Chats' as const,
      label: s.title || 'Untitled chat',
      hint: `${s.message_count} message${s.message_count === 1 ? '' : 's'}`,
      icon: <MessagesSquare size={15} />,
      run: () => {
        setView('Chat');
        setActiveThread(s.session_id);
        setSessionId(s.session_id);
      },
    }));
    return [...actions, ...views, ...chats];
  }, [sessions, theme, view, authUser?.isPlatformAdmin, setView, setActiveThread, setSessionId, toggleTheme]);

  const needle = query.trim().toLowerCase();
  const results = needle
    ? items.filter((item) => `${item.label} ${item.keywords ?? ''}`.toLowerCase().includes(needle))
    : [
        ...items.filter((item) => item.group !== 'Chats'),
        ...items.filter((item) => item.group === 'Chats').slice(0, RECENT_CHATS_WHEN_EMPTY),
      ];

  useEffect(() => {
    setActive(0);
  }, [needle]);

  // the highlight follows the active row, and keyboard moves keep it in view
  useLayoutEffect(() => {
    const row = rowRefs.current[active];
    if (!row) {
      setBox(null);
      return;
    }
    setBox({ top: row.offsetTop, height: row.offsetHeight });
    row.scrollIntoView({ block: 'nearest' });
  }, [active, results.length, open]);

  if (!open) return null;

  function choose(item: Item | undefined) {
    if (!item) return;
    onClose();
    item.run();
  }

  let lastGroup: Item['group'] | null = null;

  return createPortal(
    <div className="palette-backdrop" onMouseDown={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="palette-input-row">
          <Search size={15} className="palette-input-icon" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                if (!results.length) return;
                const n = results.length;
                setActive((i) => (event.key === 'ArrowDown' ? (i + 1) % n : (i - 1 + n) % n));
              } else if (event.key === 'Enter') {
                event.preventDefault();
                choose(results[active]);
              } else if (event.key === 'Escape') {
                event.preventDefault();
                onClose();
              }
            }}
            placeholder="Search views, chats and actions…"
            aria-label="Search views, chats and actions"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-results"
            aria-activedescendant={results[active] ? `palette-${results[active].id}` : undefined}
          />
          {query && (
            <button type="button" className="palette-clear" aria-label="Clear search" onClick={() => {
              setQuery('');
              inputRef.current?.focus();
            }}>
              <X size={12} />
            </button>
          )}
          <kbd className="palette-kbd">Esc</kbd>
        </div>

        {results.length === 0 ? (
          <div className="palette-empty">
            <span className="palette-empty-icon"><Search size={15} /></span>
            <strong>No results for “{query.trim()}”</strong>
            <span>Try a view name, a chat title, or “new chat”</span>
          </div>
        ) : (
          <div className="palette-results" id="palette-results" role="listbox" ref={listRef}>
            <span
              aria-hidden="true"
              className="palette-highlight"
              style={{ top: box?.top ?? 0, height: box?.height ?? 0, opacity: box ? 1 : 0 }}
            />
            {results.map((item, i) => {
              const header = item.group !== lastGroup ? item.group : null;
              lastGroup = item.group;
              return (
                <div key={item.id} className="palette-row-wrap">
                  {header && (
                    <div className="palette-group">
                      {header === 'Chats' && !needle ? 'Recent chats' : header}
                      {header === 'Chats' && sessions === null && ' · loading…'}
                    </div>
                  )}
                  <button
                    id={`palette-${item.id}`}
                    type="button"
                    role="option"
                    aria-selected={i === active}
                    ref={(el) => {
                      rowRefs.current[i] = el;
                    }}
                    className="palette-row"
                    onMouseMove={() => i !== active && setActive(i)}
                    onClick={() => choose(item)}
                  >
                    <span className="palette-row-icon">{item.icon}</span>
                    <span className="palette-row-label">{item.label}</span>
                    {item.hint && <span className="palette-row-hint">{item.hint}</span>}
                  </button>
                </div>
              );
            })}
          </div>
        )}
        <div className="palette-footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> move</span>
          <span><kbd>Enter</kbd> open</span>
          <span><kbd>Esc</kbd> close</span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
