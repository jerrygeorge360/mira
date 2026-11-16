import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { useApp } from '../context/AppContext';
import CommandPalette from './CommandPalette';

const VIEW_TITLES: Record<string, string> = {
  Chat: 'Chat',
  'Memory Graph': 'Memory Graph',
  'Session Working Set': 'Session Working Set',
  'Memory Pipeline': 'Memory Pipeline',
  'Memory Health': 'Memory Health',
  'Retrieval Trace': 'Retrieval Trace',
  Reflections: 'Reflections',
  Communities: 'Communities',
  Foresight: 'Foresight',
  Evaluation: 'Evaluation',
};

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);

export default function Topbar() {
  const { view, authUser } = useApp();
  const title = VIEW_TITLES[view] ?? view;
  const [paletteOpen, setPaletteOpen] = useState(false);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  function openPalette() {
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setPaletteOpen(true);
  }

  function closePalette() {
    setPaletteOpen(false);
    // hand focus back to wherever the user was (the composer, the title button, …)
    setTimeout(() => returnFocusRef.current?.focus?.(), 0);
  }

  // latest handlers/state for the window listener, which is registered once
  const openRef = useRef(paletteOpen);
  const openPaletteRef = useRef(openPalette);
  const closePaletteRef = useRef(closePalette);
  useEffect(() => {
    openRef.current = paletteOpen;
    openPaletteRef.current = openPalette;
    closePaletteRef.current = closePalette;
  });

  // ⌘K / Ctrl+K toggles the palette from anywhere in the app shell
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        if (openRef.current) closePaletteRef.current();
        else openPaletteRef.current();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="topbar">
      <button
        type="button"
        className="topbar-title"
        onClick={openPalette}
        aria-haspopup="dialog"
        aria-expanded={paletteOpen}
        title={`Jump to a view or chat (${IS_MAC ? '⌘' : 'Ctrl+'}K)`}
      >
        {title} <ChevronDown size={14} className="topbar-caret" />
      </button>
      <span className="plan-pill">
        {authUser?.provider === 'github' ? 'GitHub' : 'Demo'} · <b>{authUser?.workspaceName}</b>
      </span>
      <CommandPalette open={paletteOpen} onClose={closePalette} />
    </div>
  );
}
