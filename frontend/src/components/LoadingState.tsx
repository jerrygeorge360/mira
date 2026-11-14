import { useEffect, useState } from 'react';

/* ─────────────────────────────────────────────────────────
 * LOADING STATE — pixel-grid loader for long-running work
 *
 * Variants:
 *   drive  — square cells, chevron wavefront driving right;
 *            the 650ms cycle is shorter than the sweep, so
 *            two fronts are always in flight
 *   dots   — same wavefront, circular cells
 *   orbit  — a comet lapping the grid perimeter
 *   surfer — the drive loader paired with a looping video card
 *            (only when `videoSrc` is given; otherwise plain drive)
 *
 * Paired with a shimmering label and a live elapsed timer in
 * mono tabular figures. Reduced motion freezes the grid and the
 * shimmer (see .loading-state rules in index.css); the timer
 * still ticks.
 * ───────────────────────────────────────────────────────── */

export type LoadingVariant = 'drive' | 'dots' | 'orbit' | 'surfer';

const chevron = Array.from({ length: 9 }, (_, i) => {
  const r = Math.floor(i / 3);
  const c = i % 3;
  return (c + Math.abs(r - 1)) * 90;
});

const ORBIT_ORDER = [0, 1, 2, 5, 8, 7, 6, 3];
const orbit = Array.from({ length: 9 }, (_, i) => {
  const k = ORBIT_ORDER.indexOf(i);
  return k === -1 ? null : k * 110;
});

type Pattern = { delays: (number | null)[]; dur: number; round: boolean };

const PATTERNS: Record<'drive' | 'dots' | 'orbit', Pattern> = {
  drive: { delays: chevron, dur: 650, round: false },
  dots: { delays: chevron, dur: 650, round: true },
  orbit: { delays: orbit, dur: 950, round: false },
};

function LoaderGrid({ delays, dur, round }: Pattern) {
  return (
    <span aria-hidden="true" className="loading-grid">
      {delays.map((delay, index) => (
        <span
          key={index}
          className={`loading-cell${round ? ' round' : ''}${delay === null ? ' idle' : ''}`}
          style={
            delay === null
              ? undefined
              : { animation: `pixel-on ${dur}ms ease-in-out ${delay}ms infinite` }
          }
        />
      ))}
    </span>
  );
}

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
  variant = 'drive',
  showElapsed = true,
  videoSrc,
  className,
}: {
  label?: string;
  variant?: LoadingVariant;
  showElapsed?: boolean;
  /** Video for the surfer variant. No default: point it at an asset this project hosts. */
  videoSrc?: string;
  className?: string;
}) {
  const elapsed = useElapsed();
  const [videoOk, setVideoOk] = useState(true);
  const surfer = variant === 'surfer' && Boolean(videoSrc);
  const pattern = variant === 'surfer' ? PATTERNS.drive : PATTERNS[variant];

  const row = (
    <div className="loading-state-row">
      <LoaderGrid {...pattern} />
      <span className="loading-state-label">{label}</span>
      {showElapsed && <span className="loading-state-elapsed">{elapsed}</span>}
    </div>
  );

  return (
    <div role="status" aria-live="polite" className={`loading-state${className ? ` ${className}` : ''}`}>
      {row}
      {surfer && (
        <div className="loading-state-card">
          {videoOk ? (
            <video
              src={videoSrc}
              autoPlay
              muted
              loop
              playsInline
              onError={() => setVideoOk(false)}
            />
          ) : (
            <div className="loading-state-card-fallback">
              <LoaderGrid {...PATTERNS.drive} />
              <span>Video unavailable</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
