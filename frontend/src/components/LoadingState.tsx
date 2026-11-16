import { useEffect, useState } from 'react';
import LogoLoader from './LogoLoader';

/* ─────────────────────────────────────────────────────────
 * LOADING STATE — the MIRA mark loader for long-running work
 *
 * The animated logo (see LogoLoader) paired with a shimmering
 * label and a live elapsed timer in mono tabular figures.
 *
 * Sizes:
 *   inline — a small mark beside the label, for rows, panels
 *            and the chat's "thinking" bubble (default)
 *   page   — a large mark centred with the label under it, for
 *            whole-page waits (lazy views, the developer portal)
 *
 * Reduced motion swaps the travelling pulse for a slow fade and
 * stops the shimmer (see .loading-state rules in index.css); the
 * timer still ticks.
 * ───────────────────────────────────────────────────────── */

/** Wall-clock elapsed time. Measured from a start timestamp rather than counting
 *  ticks, so it stays correct when a background tab throttles the interval. */
function useElapsed() {
  const [start] = useState(() => Date.now());
  const [now, setNow] = useState(start);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const t = setInterval(tick, 100);
    document.addEventListener('visibilitychange', tick);
    return () => {
      clearInterval(t);
      document.removeEventListener('visibilitychange', tick);
    };
  }, []);
  const total = (now - start) / 1000;
  if (total < 60) return `${total.toFixed(1)}s`;
  return `${Math.floor(total / 60)}m ${(total % 60).toFixed(1)}s`;
}

export default function LoadingState({
  label = 'Working',
  size = 'inline',
  showElapsed = true,
  className,
}: {
  label?: string;
  size?: 'inline' | 'page';
  showElapsed?: boolean;
  className?: string;
}) {
  const elapsed = useElapsed();
  const page = size === 'page';

  return (
    <div role="status" aria-live="polite" className={`loading-state${page ? ' page' : ''}${className ? ` ${className}` : ''}`}>
      <div className="loading-state-row">
        <LogoLoader size={page ? 44 : 14} />
        <span className="loading-state-label">{label}</span>
        {showElapsed && <span className="loading-state-elapsed">{elapsed}</span>}
      </div>
    </div>
  );
}
