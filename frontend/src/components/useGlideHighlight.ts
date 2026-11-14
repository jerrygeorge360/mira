import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, RefObject } from 'react';

/**
 * One highlight that glides to whichever row the pointer is over, instead of
 * each row toggling its own hover background. Rows opt in with `data-glide-row`.
 * The container must be `position: relative`; render a `<span style={style} />`
 * as its first child. Measures with offsetTop/Left, so it scrolls with content.
 */
export function useGlideHighlight<T extends HTMLElement>(): {
  ref: RefObject<T | null>;
  style: CSSProperties;
  active: boolean;
} {
  const ref = useRef<T>(null);
  const [box, setBox] = useState<{ top: number; left: number; width: number; height: number } | null>(null);
  const [active, setActive] = useState(false);

  useEffect(() => {
    const container = ref.current;
    if (!container) return;
    const onOver = (event: PointerEvent) => {
      const row = (event.target as Element).closest<HTMLElement>('[data-glide-row]');
      if (!row || !container.contains(row)) return;
      setBox({ top: row.offsetTop, left: row.offsetLeft, width: row.offsetWidth, height: row.offsetHeight });
      setActive(true);
    };
    const onLeave = () => setActive(false);
    container.addEventListener('pointerover', onOver);
    container.addEventListener('pointerleave', onLeave);
    return () => {
      container.removeEventListener('pointerover', onOver);
      container.removeEventListener('pointerleave', onLeave);
    };
  }, []);

  return {
    ref,
    active,
    style: {
      top: box?.top ?? 0,
      left: box?.left ?? 0,
      width: box?.width ?? 0,
      height: box?.height ?? 0,
      opacity: active && box ? 1 : 0,
    },
  };
}
