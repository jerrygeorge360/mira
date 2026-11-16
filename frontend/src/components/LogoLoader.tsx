import { useState, type CSSProperties } from 'react';

/* ─────────────────────────────────────────────────────────
 * LOGO LOADER — the MIRA mark as a loading animation
 *
 * The mark is five memory nodes joined into an "M". While
 * something loads, a pulse of light travels through it in the
 * order the M is drawn — bottom-left, up, down to the centre,
 * up, down to bottom-right — lighting each node and drawing
 * each link as it passes, like a memory being retrieved. The
 * lit stretch moves along the mark and then fades, so it reads
 * as one signal travelling rather than everything blinking.
 *
 * Geometry is the supplied logo (mira logo.svg), same as
 * BrandMark. Pure CSS keyframes with per-element delays: no
 * JavaScript timers, so it keeps running smoothly while the
 * main thread is busy loading. Reduced motion shows the mark
 * with a slow, gentle fade instead of the travelling pulse.
 *
 * `active={false}` settles it into the plain logo: the pulse
 * fades out and the resting mark eases back to full strength.
 * That lets one element be both the logo and the loader — the
 * chat's assistant avatar animates while MIRA is working and
 * returns to the logo when the reply is done.
 *
 * Every loader shares one clock (a negative delay set from
 * performance.now() at mount), so when React swaps one loader
 * for another mid-wait the pulse carries on instead of jumping
 * back to the start.
 * ───────────────────────────────────────────────────────── */

// Nodes and links in the order the pulse visits them.
const NODES: [number, number][] = [
  [95, 453],
  [126, 246],
  [306, 353],
  [483, 246],
  [514, 453],
];
// Each link runs from the node the pulse leaves to the node it reaches.
const LINKS: [number, number, number, number][] = [
  [94.17, 420.06, 114.48, 285.76],
  [154.38, 263.92, 271.38, 332.92],
  [332.62, 335.92, 449.62, 266.92],
  [489.83, 285.76, 510.14, 420.06],
];

/** One step of the pulse: node, then the link after it, then the next node… */
const STEP_MS = 95;
const CYCLE_MS = 1700;

export default function LogoLoader({
  size = 20,
  className,
  label,
  active = true,
}: {
  /** height in px; the mark is 1.67× as wide */
  size?: number;
  className?: string;
  /** set when the loader stands alone; inside LoadingState the text label speaks for it */
  label?: string;
  /** false shows the resting logo; the pulse fades out and stops */
  active?: boolean;
}) {
  const [phase] = useState(() => performance.now() % CYCLE_MS);
  const delay = (step: number): CSSProperties => ({
    animationDelay: `${step * STEP_MS - phase}ms`,
    animationDuration: `${CYCLE_MS}ms`,
  });
  return (
    <svg
      className={`logo-loader${active ? '' : ' idle'}${className ? ` ${className}` : ''}`}
      viewBox="40 191 529 317"
      height={size}
      width={(size * 529) / 317}
      fill="none"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {/* the resting mark, faint */}
      <g className="logo-loader-base">
        {LINKS.map(([x1, y1, x2, y2], i) => (
          <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} strokeWidth="30" />
        ))}
        {NODES.map(([cx, cy], i) => (
          <circle key={i} cx={cx} cy={cy} r="34.5" strokeWidth="31" />
        ))}
      </g>

      {/* the pulse: each link draws in the direction of travel, each node lights as it is reached */}
      <g className="logo-loader-pulse">
        {LINKS.map(([x1, y1, x2, y2], i) => (
          <line
            key={i}
            className="logo-loader-link"
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            strokeWidth="30"
            pathLength={1}
            style={delay(i * 2 + 1)}
          />
        ))}
        {NODES.map(([cx, cy], i) => (
          <circle key={i} className="logo-loader-node" cx={cx} cy={cy} r="34.5" strokeWidth="31" style={delay(i * 2)} />
        ))}
      </g>
    </svg>
  );
}
