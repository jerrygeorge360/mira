interface BrandMarkProps {
  className?: string;
  /** Height in px. The mark is 1.67× as wide; the lockup 3.15×. */
  size?: number;
  title?: string;
  /** Draw the full logo: the node-graph "M" followed by the letters "IRA". */
  lockup?: boolean;
}

/* The MIRA logo: five memory nodes joined into an "M". In the full logo the
 * graph stands in for the first letter, so the lockup is the mark plus "IRA";
 * never set the word "MIRA" in type next to it.
 * Geometry is taken from the supplied logo files. It draws in currentColor,
 * and the rings are stroked so the page shows through their centres. */
const MARK_W = 529;
const LOCKUP_W = 997;
const H = 317;

const NODES: [number, number][] = [
  [95, 453],
  [126, 246],
  [306, 353],
  [483, 246],
  [514, 453],
];
const EDGES: [number, number, number, number][] = [
  [94.17, 420.06, 114.48, 285.76],
  [154.38, 263.92, 271.38, 332.92],
  [449.62, 266.92, 332.62, 335.92],
  [510.14, 420.06, 489.83, 285.76],
];
const IRA =
  'M613.648 436V249.12H638.736V436H613.648ZM693.636 436V248.096H718.724V436H693.636ZM809.092 436L747.14 352.8H776.58L839.556 436H809.092ZM709.252 368.416V346.144H759.428C767.279 346.144 774.02 344.523 779.652 341.28C785.284 338.037 789.636 333.6 792.708 327.968C795.78 322.165 797.316 315.595 797.316 308.256C797.316 300.917 795.78 294.432 792.708 288.8C789.636 282.997 785.284 278.475 779.652 275.232C774.02 271.819 767.279 270.112 759.428 270.112H709.252V248.096H754.82C768.473 248.096 780.42 250.144 790.66 254.24C800.9 258.336 808.836 264.651 814.468 273.184C820.1 281.717 822.916 292.725 822.916 306.208V310.304C822.916 323.787 820.015 334.795 814.212 343.328C808.58 351.861 800.644 358.176 790.404 362.272C780.335 366.368 768.473 368.416 754.82 368.416H709.252ZM852.918 436L920.246 249.12H962.742L1032.12 436H1006.26L943.542 265.504L955.83 271.648H925.622L938.678 265.504L878.006 436H852.918ZM893.11 380.192L901.558 357.664H982.198L990.646 380.192H893.11Z';

export default function BrandMark({ className, size = 24, title, lockup = false }: BrandMarkProps) {
  const width = lockup ? LOCKUP_W : MARK_W;
  return (
    <svg
      aria-hidden={title ? undefined : true}
      aria-label={title}
      className={className}
      height={size}
      role={title ? 'img' : undefined}
      viewBox={`40 191 ${width} ${H}`}
      width={(size * width) / H}
      fill="none"
    >
      {EDGES.map(([x1, y1, x2, y2]) => (
        <line key={`${x1}-${y1}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="currentColor" strokeWidth="30" />
      ))}
      {NODES.map(([cx, cy]) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="34.5" stroke="currentColor" strokeWidth="31" />
      ))}
      {lockup && <path d={IRA} fill="currentColor" />}
    </svg>
  );
}
