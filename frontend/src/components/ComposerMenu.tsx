import { useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Check } from 'lucide-react';

/* ─────────────────────────────────────────────────────────
 * COMPOSER MENU — a popover list that grows up from the chat
 * composer. One highlight glides to the active row instead of
 * each row toggling its own background. Keyboard handling lives
 * with the owner (the textarea keeps focus); this only renders.
 * ───────────────────────────────────────────────────────── */

export type MenuRow = {
  key: string;
  label: string;
  desc?: string;
  icon?: ReactNode;
  selected?: boolean;
};

export default function ComposerMenu({
  id,
  rows,
  active,
  onActiveChange,
  onPick,
  footer,
  empty,
  className,
  label,
  clearOnLeave = false,
}: {
  id: string;
  rows: MenuRow[];
  /** index of the highlighted row, or null for no highlight */
  active: number | null;
  onActiveChange: (index: number | null) => void;
  onPick: (row: MenuRow) => void;
  footer?: string;
  empty?: string;
  className?: string;
  label: string;
  /** drop the highlight when the pointer leaves (hover-only menus); keyboard menus keep it */
  clearOnLeave?: boolean;
}) {
  const rowRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [box, setBox] = useState<{ top: number; height: number } | null>(null);

  useLayoutEffect(() => {
    const target = active === null ? null : rowRefs.current[active];
    if (target) setBox({ top: target.offsetTop, height: target.offsetHeight });
  }, [active, rows.length]);

  return (
    <div
      id={id}
      role="listbox"
      aria-label={label}
      className={`composer-menu${className ? ` ${className}` : ''}`}
      onMouseLeave={clearOnLeave ? () => onActiveChange(null) : undefined}
    >
      <span
        aria-hidden="true"
        className="composer-menu-highlight"
        style={{ top: box?.top ?? 0, height: box?.height ?? 0, opacity: box && active !== null && rows.length ? 1 : 0 }}
      />
      {rows.map((row, i) => (
        <button
          key={row.key}
          id={`${id}-${row.key}`}
          type="button"
          role="option"
          aria-selected={active === i}
          ref={(el) => {
            rowRefs.current[i] = el;
          }}
          className="composer-menu-row"
          // keep focus in the textarea
          onMouseDown={(event) => event.preventDefault()}
          onMouseEnter={() => onActiveChange(i)}
          onClick={() => onPick(row)}
        >
          {row.icon && <span className="composer-menu-icon">{row.icon}</span>}
          <span className="composer-menu-label">{row.label}</span>
          {row.desc && <span className="composer-menu-desc">{row.desc}</span>}
          {row.selected !== undefined && (
            <Check size={13} strokeWidth={2.5} className={`composer-menu-check${row.selected ? '' : ' hidden'}`} />
          )}
        </button>
      ))}
      {!rows.length && empty && <div className="composer-menu-empty">{empty}</div>}
      {footer && <div className="composer-menu-footer">{footer}</div>}
    </div>
  );
}
