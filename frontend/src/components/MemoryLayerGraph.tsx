import { useEffect, useRef, useState } from 'react';
import BrandMark from './BrandMark';

/* ─────────────────────────────────────────────────────────
 * MEMORY LAYER GRAPH — the landing page's pipeline diagram
 *
 * MIRA sits at the hub; the four memory layers are cards around
 * it. Each pipeline stage touches one layer, and the diagram
 * shows which and in which direction:
 *
 *   write  hub → layer   (observe, promote, consolidate, supersede)
 *   read   layer → hub   (recall, foresight)
 *
 * Per stage the connector draws in the signal colour, a dot
 * travels along it, and the card it lands on lights up. Layers
 * touched earlier in the run keep a small check.
 *
 * Robustness, compared with the first version:
 *   - the dot follows the connector with SVG <animateMotion>, not
 *     a CSS transform built from custom properties (which Safari
 *     and older engines animate unreliably on SVG elements)
 *   - text sits inside the cards at a size picked per layout, and
 *     a narrow container gets its own stacked layout, so labels
 *     never scale down to unreadable on a phone
 *   - everything is keyed on `runKey`, so each stage replays from
 *     the start; reduced motion keeps the colours and drops motion
 * ───────────────────────────────────────────────────────── */

export type GraphLayer = { level: string; title: string };

type Point = { x: number; y: number };
type Layout = {
  w: number;
  h: number;
  hub: Point;
  hubSize: number;
  card: { w: number; h: number };
  /** card centres, in layer order L1…L4 */
  cards: Point[];
  font: { level: number; title: number };
};

// Wide: the four layers at the corners of the hub, two each side.
const WIDE: Layout = {
  w: 640,
  h: 300,
  hub: { x: 320, y: 150 },
  hubSize: 64,
  card: { w: 176, h: 56 },
  cards: [
    { x: 108, y: 62 },
    { x: 532, y: 62 },
    { x: 108, y: 238 },
    { x: 532, y: 238 },
  ],
  font: { level: 11, title: 13 },
};

// Narrow: two layers above the hub, two below, each full-width-ish.
const NARROW: Layout = {
  w: 340,
  h: 420,
  hub: { x: 170, y: 210 },
  hubSize: 60,
  card: { w: 150, h: 58 },
  cards: [
    { x: 85, y: 44 },
    { x: 255, y: 44 },
    { x: 85, y: 376 },
    { x: 255, y: 376 },
  ],
  font: { level: 12, title: 13.5 },
};

/** Where a connector leaves a card: the middle of the edge facing the hub. */
function cardAnchor(layout: Layout, i: number): Point {
  const c = layout.cards[i];
  const { w, h } = layout.card;
  const dx = layout.hub.x - c.x;
  const dy = layout.hub.y - c.y;
  // wide layout: leave from the inner side; narrow: from the top/bottom edge
  return Math.abs(dx) / w > Math.abs(dy) / h
    ? { x: c.x + Math.sign(dx) * (w / 2), y: c.y }
    : { x: c.x, y: c.y + Math.sign(dy) * (h / 2) };
}

/** Where a connector meets the hub's rounded square. */
function hubAnchor(layout: Layout, from: Point): Point {
  const { hub, hubSize } = layout;
  const dx = from.x - hub.x;
  const dy = from.y - hub.y;
  const half = hubSize / 2;
  const t = half / Math.max(Math.abs(dx), Math.abs(dy));
  return { x: hub.x + dx * t, y: hub.y + dy * t };
}

/** A soft curve from the card to the hub (control point bends toward the hub's row/column). */
function connector(layout: Layout, i: number) {
  const a = cardAnchor(layout, i);
  const b = hubAnchor(layout, a);
  const horizontal = a.y === layout.cards[i].y;
  const c = horizontal ? { x: (a.x + b.x) / 2, y: a.y } : { x: a.x, y: (a.y + b.y) / 2 };
  return { from: a, to: b, d: `M${a.x} ${a.y} Q${c.x} ${c.y} ${b.x} ${b.y}`, reverse: `M${b.x} ${b.y} Q${c.x} ${c.y} ${a.x} ${a.y}` };
}

function useLayout() {
  const ref = useRef<HTMLDivElement>(null);
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setNarrow(el.clientWidth < 520);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return { ref, layout: narrow ? NARROW : WIDE };
}

export default function MemoryLayerGraph({
  layers,
  active,
  flow,
  visited,
  runKey,
  label,
}: {
  layers: GraphLayer[];
  /** index of the layer the current stage touches */
  active: number;
  flow: 'write' | 'read';
  /** layers touched earlier in this run */
  visited: ReadonlySet<number>;
  /** changes whenever the stage changes, to replay the motion */
  runKey: string | number;
  /** what the diagram shows right now, for screen readers */
  label: string;
}) {
  const { ref, layout } = useLayout();
  const { card, hub, hubSize } = layout;
  const live = connector(layout, active);
  // the dot travels in the direction the data moves
  const motionPath = flow === 'write' ? live.reverse : live.d;

  // SVG animation times count from page load, so a dot inserted later would already be
  // "finished". Both animations wait (begin="indefinite") and are started here, once per
  // stage, a beat after the connector starts drawing.
  const motionRef = useRef<SVGAnimateMotionElement>(null);
  const fadeRef = useRef<SVGAnimateElement>(null);
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    motionRef.current?.beginElementAt(0.15);
    fadeRef.current?.beginElementAt(0.15);
  }, [runKey, layout]);

  return (
    <div ref={ref} className="lp-graph-wrap">
      <svg className="lp-graph" viewBox={`0 0 ${layout.w} ${layout.h}`} role="img" aria-label={label}>
        {/* idle connectors */}
        {layout.cards.map((_, i) => (
          <path key={i} className="lp-graph-spoke" d={connector(layout, i).d} />
        ))}

        {/* the live connector draws in, then the dot runs along it */}
        <path key={`live-${runKey}`} className="lp-graph-spoke-live" d={motionPath} pathLength={1} />
        <circle key={`dot-${runKey}-${layout.w}`} className="lp-graph-packet" r={4.5} opacity={0}>
          <animateMotion ref={motionRef} dur="0.9s" begin="indefinite" fill="freeze" path={motionPath} keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines="0.65 0 0.35 1" />
          <animate ref={fadeRef} attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.85;1" dur="1.2s" begin="indefinite" fill="freeze" />
        </circle>

        {/* hub */}
        <g className="lp-graph-hub" data-receiving={flow === 'read' || undefined} key={`hub-${runKey}`}>
          <rect x={hub.x - hubSize / 2} y={hub.y - hubSize / 2} width={hubSize} height={hubSize} rx={16} />
          <g transform={`translate(${hub.x - 22} ${hub.y - 13.2})`}>
            <BrandMark size={26.4} />
          </g>
        </g>

        {/* layer cards */}
        {layers.map((layer, i) => {
          const c = layout.cards[i];
          const state = i === active ? 'active' : visited.has(i) ? 'visited' : 'idle';
          const x = c.x - card.w / 2;
          const y = c.y - card.h / 2;
          return (
            <g key={layer.level} className="lp-graph-node" data-state={state}>
              <rect className="lp-graph-card" x={x} y={y} width={card.w} height={card.h} rx={12} />
              {state === 'active' && (
                <rect key={`pulse-${runKey}`} className="lp-graph-pulse" x={x} y={y} width={card.w} height={card.h} rx={12} />
              )}
              <text className="lp-graph-level" x={x + 14} y={y + 22} fontSize={layout.font.level}>
                {layer.level}
              </text>
              <text className="lp-graph-title" x={x + 14} y={y + 41} fontSize={layout.font.title}>
                {layer.title}
              </text>
              {state === 'visited' && (
                <g className="lp-graph-tick" transform={`translate(${x + card.w - 18} ${y + 18})`}>
                  <circle r={7} />
                  <path d="M-3 0 L-1 2.2 L3 -2.2" />
                </g>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
