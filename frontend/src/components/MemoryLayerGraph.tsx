import type { CSSProperties } from 'react';
import BrandMark from './BrandMark';

/* ─────────────────────────────────────────────────────────
 * MEMORY LAYER GRAPH — the star diagram on the landing page
 *
 * MIRA sits at the hub; the four memory layers are the points.
 * Each pipeline stage touches one layer, and the diagram shows
 * which one and in which direction:
 *
 *   write  hub → layer   (observe, promote, consolidate, supersede)
 *   read   layer → hub   (recall, foresight)
 *
 * Per stage: the spoke draws itself in the signal colour, a packet
 * travels along it, and a ring pulses once where it lands. Layers
 * already touched in this run keep a small filled dot.
 *
 * The moving parts are keyed on `runKey`, so each stage change
 * remounts them and the CSS animations play from the start. With
 * reduced motion the packet and pulse are hidden and only the
 * colours change.
 * ───────────────────────────────────────────────────────── */

export type GraphLayer = { level: string; title: string };

const W = 560;
const H = 344;
const HUB = { x: 280, y: 166, r: 36 };
const NODE_R = 27;
const POINTS = [
  { x: 96, y: 70 },
  { x: 464, y: 70 },
  { x: 96, y: 262 },
  { x: 464, y: 262 },
];

/** The spoke between the hub's edge and a layer node's edge. */
function spoke(index: number) {
  const p = POINTS[index];
  const dx = p.x - HUB.x;
  const dy = p.y - HUB.y;
  const len = Math.hypot(dx, dy);
  const ux = dx / len;
  const uy = dy / len;
  return {
    hub: { x: HUB.x + ux * HUB.r, y: HUB.y + uy * HUB.r },
    node: { x: p.x - ux * NODE_R, y: p.y - uy * NODE_R },
  };
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
  const live = spoke(active);
  const from = flow === 'write' ? live.hub : live.node;
  const to = flow === 'write' ? live.node : live.hub;
  const landing = flow === 'write' ? { ...POINTS[active], r: NODE_R } : HUB;

  return (
    <svg className="lp-graph" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
      {/* promotion path between layers: working set → hot → durable */}
      <path
        className="lp-graph-path"
        d={`M${POINTS[0].x + NODE_R} ${POINTS[0].y}H${POINTS[1].x - NODE_R}M${POINTS[1].x} ${POINTS[1].y + NODE_R}V${POINTS[3].y - NODE_R}`}
      />

      {POINTS.map((_, i) => {
        const s = spoke(i);
        return <line key={i} className="lp-graph-spoke" x1={s.hub.x} y1={s.hub.y} x2={s.node.x} y2={s.node.y} />;
      })}

      {/* the live spoke, drawn in the direction the data moves */}
      <line
        key={`spoke-${runKey}`}
        className="lp-graph-spoke-live"
        pathLength={1}
        x1={from.x}
        y1={from.y}
        x2={to.x}
        y2={to.y}
      />

      <circle
        key={`pulse-${runKey}`}
        className="lp-graph-pulse"
        cx={landing.x}
        cy={landing.y}
        r={landing.r}
      />

      <g className="lp-graph-hub">
        <circle cx={HUB.x} cy={HUB.y} r={HUB.r} />
        <g transform={`translate(${HUB.x - 20} ${HUB.y - 12})`}>
          <BrandMark size={24} />
        </g>
      </g>

      {layers.map((layer, i) => {
        const p = POINTS[i];
        const state = i === active ? 'active' : visited.has(i) ? 'visited' : 'idle';
        return (
          <g key={layer.level} className="lp-graph-node" data-state={state}>
            <circle cx={p.x} cy={p.y} r={NODE_R} />
            <text className="lp-graph-level" x={p.x} y={p.y + 4} textAnchor="middle">
              {layer.level}
            </text>
            <text className="lp-graph-title" x={p.x} y={p.y + NODE_R + 20} textAnchor="middle">
              {layer.title}
            </text>
            {state === 'visited' && <circle className="lp-graph-tick" cx={p.x + 19} cy={p.y - 19} r={4} />}
          </g>
        );
      })}

      <circle
        key={`packet-${runKey}`}
        className="lp-graph-packet"
        r={5}
        style={{ '--x1': `${from.x}px`, '--y1': `${from.y}px`, '--x2': `${to.x}px`, '--y2': `${to.y}px` } as CSSProperties}
      />
    </svg>
  );
}
