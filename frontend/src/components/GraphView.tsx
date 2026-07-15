import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { GRAPH_DATA } from '../data/mockData';

export interface Node extends d3.SimulationNodeDatum {
  id: string;
  name: string;
  type: string;
  val: number;
  color: string;
  headline: string;
  summary: string;
  status: string;
  sourceTable?: string;
  sourceId?: string;
  createdAt?: string;
  metadata?: Record<string, unknown>;
}

export interface Link extends d3.SimulationLinkDatum<Node> {
  id?: string;
  type: string;
  confidence?: number;
  status?: string;
  sourceObservations?: string[];
  validFrom?: string;
  validUntil?: string;
  createdAt?: string;
  invalidatedAt?: string;
  metadata?: Record<string, unknown>;
}

export interface GraphData {
  nodes: Node[];
  links: Link[];
}

interface Props {
  height?: number;
  data?: GraphData;
}

type LabelMode = 'key' | 'entities' | 'none';

export default function GraphView({ height = 460, data }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<Link | null>(null);
  const [labelMode, setLabelMode] = useState<LabelMode>('key');

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const svg = d3.select<SVGSVGElement, unknown>(el);
    const W = el.clientWidth || 800;
    const H = height;

    svg.selectAll('*').remove();

    const graph = data ?? (GRAPH_DATA as unknown as GraphData);
    const nodes: Node[] = graph.nodes.map(n => ({ ...n } as Node));
    const links: Link[] = graph.links.map(l => ({ ...l } as Link));

    const sim = d3
      .forceSimulation<Node>(nodes)
      .force('link', d3.forceLink<Node, Link>(links).id(d => d.id).distance(90))
      .force('charge', d3.forceManyBody().strength(-250))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collision', d3.forceCollide<Node>(d => d.val * 3.5));

    const g = svg.append('g');

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on('zoom', ev => g.attr('transform', ev.transform));
    zoomRef.current = zoom;
    svg.call(zoom);

    // links
    const linkLayer = g.append('g');
    const link = linkLayer
      .selectAll<SVGLineElement, Link>('line.graph-link-line')
      .data(links)
      .join('line')
      .attr('class', 'graph-link-line')
      .attr('stroke', d => relationshipStyle(d.type).color)
      .attr('stroke-width', d => relationshipStyle(d.type).width)
      .attr('stroke-dasharray', d => relationshipStyle(d.type).dash)
      .attr('stroke-opacity', d => relationshipStyle(d.type).opacity);

    const linkHitbox = linkLayer
      .append('g')
      .selectAll<SVGLineElement, Link>('line.graph-link-hitbox')
      .data(links)
      .join('line')
      .attr('class', 'graph-link-hitbox')
      .attr('stroke', 'transparent')
      .attr('stroke-width', 14)
      .style('cursor', 'pointer')
      .on('click', (ev, d) => {
        ev.stopPropagation();
        setSelectedNode(null);
        setSelectedEdge({ ...d });
      });

    const edgeLabel = g
      .append('g')
      .selectAll<SVGTextElement, Link>('text.graph-edge-label')
      .data(links)
      .join('text')
      .attr('class', 'graph-edge-label')
      .text(d => d.type || 'RELATED')
      .attr('text-anchor', 'middle')
      .attr('font-size', 9)
      .attr('font-family', 'Inter, sans-serif')
      .attr('font-weight', 700)
      .attr('fill', d => relationshipStyle(d.type).color)
      .attr('paint-order', 'stroke')
      .attr('stroke', 'var(--surface)')
      .attr('stroke-width', 4)
      .attr('stroke-linejoin', 'round')
      .style('cursor', 'pointer')
      .on('click', (ev, d) => {
        ev.stopPropagation();
        setSelectedNode(null);
        setSelectedEdge({ ...d });
      });

    // nodes
    const node = g
      .append('g')
      .selectAll<SVGCircleElement, Node>('circle')
      .data(nodes)
      .join('circle')
      .attr('r', d => d.val * 2.8)
      .attr('fill', d => d.color)
      .attr('fill-opacity', 0.85)
      .attr('stroke', 'var(--surface)')
      .attr('stroke-width', 2)
      .style('cursor', 'pointer')
      .on('click', (ev, d) => {
        ev.stopPropagation();
        setSelectedEdge(null);
        setSelectedNode(prev => (prev?.id === d.id ? null : d));
      })
      .call(
        d3.drag<SVGCircleElement, Node>()
          .on('start', (ev, d) => { if (!ev.active) sim.alphaTarget(0.25).restart(); d.fx = d.x; d.fy = d.y; })
          .on('drag', (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
          .on('end', (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    const nodeLabel = g
      .append('g')
      .selectAll<SVGTextElement, Node>('text.graph-node-label')
      .data(nodes.filter(node => shouldShowNodeLabel(node, labelMode)))
      .join('text')
      .attr('class', 'graph-node-label')
      .text(d => shortLabel(d.name))
      .attr('text-anchor', 'middle')
      .attr('dy', d => -(d.val * 2.8 + 8))
      .attr('font-size', d => d.type === 'entity' ? 10 : 9)
      .attr('font-family', 'Inter, sans-serif')
      .attr('font-weight', 750)
      .attr('fill', 'var(--text)')
      .attr('paint-order', 'stroke')
      .attr('stroke', 'var(--surface)')
      .attr('stroke-width', 4)
      .attr('stroke-linejoin', 'round')
      .style('cursor', 'pointer')
      .on('click', (ev, d) => {
        ev.stopPropagation();
        setSelectedEdge(null);
        setSelectedNode(prev => (prev?.id === d.id ? null : d));
      });

    svg.on('click', () => {
      setSelectedNode(null);
      setSelectedEdge(null);
    });

    sim.on('tick', () => {
      link
        .attr('x1', d => (d.source as Node).x ?? 0)
        .attr('y1', d => (d.source as Node).y ?? 0)
        .attr('x2', d => (d.target as Node).x ?? 0)
        .attr('y2', d => (d.target as Node).y ?? 0);
      linkHitbox
        .attr('x1', d => (d.source as Node).x ?? 0)
        .attr('y1', d => (d.source as Node).y ?? 0)
        .attr('x2', d => (d.target as Node).x ?? 0)
        .attr('y2', d => (d.target as Node).y ?? 0);
      edgeLabel
        .attr('x', d => (((d.source as Node).x ?? 0) + ((d.target as Node).x ?? 0)) / 2)
        .attr('y', d => (((d.source as Node).y ?? 0) + ((d.target as Node).y ?? 0)) / 2);
      node.attr('cx', d => d.x ?? 0).attr('cy', d => d.y ?? 0);
      nodeLabel.attr('x', d => d.x ?? 0).attr('y', d => d.y ?? 0);
    });

    return () => {
      sim.stop();
      zoomRef.current = null;
    };
  }, [height, data, labelMode]);

  function zoomBy(factor: number) {
    const el = svgRef.current;
    const zoom = zoomRef.current;
    if (!el || !zoom) return;
    d3.select(el).transition().duration(180).call(zoom.scaleBy, factor);
  }

  function resetZoom() {
    const el = svgRef.current;
    const zoom = zoomRef.current;
    if (!el || !zoom) return;
    d3.select(el).transition().duration(180).call(zoom.transform, d3.zoomIdentity);
  }

  const TYPE_COLORS: Record<string, string> = {
    entity: '#d97757',
    observation: '#5b8def',
    reflection: '#9b7ad6',
    community: '#3fb27f',
    foresight: '#e0a13a',
    atomic_fact: '#8a8f99',
  };

  return (
    <div className="graph-container">
      <div className="graph-toolbar" aria-label="Graph controls">
        <button type="button" onClick={() => zoomBy(1.25)} aria-label="Zoom in">+</button>
        <button type="button" onClick={() => zoomBy(0.8)} aria-label="Zoom out">−</button>
        <button type="button" onClick={resetZoom}>Reset</button>
      </div>
      <div className="graph-label-toolbar" aria-label="Graph label mode">
        {[
          ['key', 'Key labels'],
          ['entities', 'Entities'],
          ['none', 'No labels'],
        ].map(([mode, label]) => (
          <button
            key={mode}
            type="button"
            className={labelMode === mode ? 'active' : ''}
            onClick={() => setLabelMode(mode as LabelMode)}
          >
            {label}
          </button>
        ))}
      </div>
      <svg ref={svgRef} className="graph-canvas" style={{ height }} />
      {(selectedNode || selectedEdge) && (
        <div className="graph-inspector">
          {selectedNode && (
            <>
              <div className="graph-inspector-kicker">{selectedNode.type}</div>
              <div className="graph-inspector-title">{selectedNode.name}</div>
              <div className="graph-inspector-sub">{selectedNode.headline || selectedNode.sourceTable || 'Graph node'}</div>
              <div className="graph-inspector-grid">
                <InspectorField label="Source" value={sourceLabel(selectedNode.sourceTable, selectedNode.sourceId)} />
                <InspectorField label="Created" value={formatCompactDate(selectedNode.createdAt)} />
                <InspectorField label="Status" value={selectedNode.status || 'active'} tone="accent" />
              </div>
              {selectedNode.summary && <div className="graph-inspector-body">{selectedNode.summary}</div>}
              <details className="graph-inspector-details">
                <summary>Advanced details</summary>
                <InspectorField label="Node ID" value={selectedNode.id} />
                {selectedNode.metadata && <pre>{JSON.stringify(selectedNode.metadata, null, 2)}</pre>}
              </details>
            </>
          )}
          {selectedEdge && (
            <>
              <div className="graph-inspector-kicker">{relationshipCategory(selectedEdge.type)} relationship</div>
              <div className="graph-inspector-title">{selectedEdge.type || 'RELATED'}</div>
              <div className="graph-inspector-sub">
                {nodeName(selectedEdge.source)} → {nodeName(selectedEdge.target)}
              </div>
              <div className="graph-inspector-grid">
                <InspectorField label="Status" value={selectedEdge.status || 'active'} tone="accent" />
                <InspectorField label="Confidence" value={formatConfidence(selectedEdge.confidence)} />
                <InspectorField label="Valid window" value={formatValidity(selectedEdge.validFrom, selectedEdge.validUntil)} />
                <InspectorField label="Created" value={formatCompactDate(selectedEdge.createdAt)} />
              </div>
              <div className="graph-inspector-body">{relationshipDescription(selectedEdge.type)}</div>
              <details className="graph-inspector-details">
                <summary>Advanced details</summary>
                <InspectorField label="Edge ID" value={selectedEdge.id} />
                <InspectorField label="Valid from" value={formatCompactDate(selectedEdge.validFrom)} />
                <InspectorField label="Valid until" value={formatCompactDate(selectedEdge.validUntil)} />
                <InspectorField label="Invalidated at" value={formatCompactDate(selectedEdge.invalidatedAt)} />
                <InspectorField
                  label="Evidence"
                  value={selectedEdge.sourceObservations?.length ? selectedEdge.sourceObservations.join(', ') : undefined}
                />
                {selectedEdge.metadata && <pre>{JSON.stringify(selectedEdge.metadata, null, 2)}</pre>}
              </details>
            </>
          )}
          <button className="graph-inspector-close" onClick={() => { setSelectedNode(null); setSelectedEdge(null); }} aria-label="Close graph inspector">
            ×
          </button>
        </div>
      )}
      <div className="graph-legend">
        {Object.entries(TYPE_COLORS).map(([type, color]) => (
          <div key={type} className="legend-item">
            <div className="legend-dot" style={{ background: color }} />
            {type.replace('_', ' ')}
          </div>
        ))}
      </div>
      <div className="graph-legend relationship-legend">
        <div className="legend-item">
          <span className="legend-line conflict" />
          contradicts
        </div>
        <div className="legend-item">
          <span className="legend-line supersession" />
          superseded
        </div>
        <div className="legend-item">
          <span className="legend-line evidence" />
          mentions
        </div>
        <div className="legend-item">
          <span className="legend-line derived" />
          derived
        </div>
      </div>
    </div>
  );
}

function nodeName(node: string | number | Node | undefined): string {
  if (node && typeof node === 'object' && 'name' in node) return node.name;
  return String(node ?? 'unknown');
}

function shortLabel(value: string): string {
  const label = value.trim();
  if (label.length <= 22) return label;
  return `${label.slice(0, 19).trimEnd()}…`;
}

function shouldShowNodeLabel(node: Node, mode: LabelMode): boolean {
  if (mode === 'none') return false;
  if (mode === 'entities') return node.type === 'entity';
  return ['entity', 'community', 'foresight'].includes(node.type) || node.val >= 11;
}

function relationshipCategory(type: string | undefined): string {
  const normalized = (type || '').toUpperCase();
  if (normalized === 'SUPERSEDED_BY') return 'change';
  if (normalized === 'CONTRADICTS') return 'conflict';
  if (['CAUSED_BY', 'LEADS_TO'].includes(normalized)) return 'causal';
  if (['MENTIONS', 'DERIVED_FROM'].includes(normalized)) return 'evidence';
  return 'other';
}

function relationshipStyle(type: string | undefined): {
  color: string;
  dash: string;
  opacity: number;
  width: number;
} {
  const normalized = (type || '').toUpperCase();
  if (normalized === 'CONTRADICTS') {
    return { color: '#ef5b55', dash: '6 4', opacity: 0.9, width: 2.4 };
  }
  if (normalized === 'SUPERSEDED_BY') {
    return { color: '#e0a13a', dash: '10 4', opacity: 0.9, width: 2.3 };
  }
  if (['CAUSED_BY', 'LEADS_TO'].includes(normalized)) {
    return { color: '#3fb27f', dash: '4 3', opacity: 0.82, width: 2 };
  }
  if (normalized === 'DERIVED_FROM') {
    return { color: '#9b7ad6', dash: '2 3', opacity: 0.78, width: 1.8 };
  }
  if (normalized === 'MENTIONS') {
    return { color: '#5b8def', dash: '', opacity: 0.58, width: 1.5 };
  }
  return { color: 'var(--border-strong)', dash: '', opacity: 0.62, width: 1.5 };
}

function relationshipDescription(type: string | undefined): string {
  const normalized = (type || '').toUpperCase();
  if (normalized === 'CONTRADICTS') return 'Preserves an unresolved conflict instead of deleting either memory.';
  if (normalized === 'SUPERSEDED_BY') return 'Marks an older memory as replaced by a newer correction or transition.';
  if (normalized === 'DERIVED_FROM') return 'Links a synthesized memory back to the evidence it was derived from.';
  if (normalized === 'MENTIONS') return 'Connects an observation to an entity it mentions.';
  if (normalized === 'CAUSED_BY') return 'Represents a causal relationship between memories.';
  if (normalized === 'LEADS_TO') return 'Represents a directional consequence or transition.';
  return 'A typed relationship stored in the durable memory graph.';
}

function InspectorField({
  label,
  value,
  tone,
}: {
  label: string;
  value?: string | number | null;
  tone?: 'accent';
}) {
  if (value === undefined || value === null || value === '') return null;
  return (
    <div className="graph-inspector-field">
      <span>{label}</span>
      <strong className={tone === 'accent' ? 'accent' : undefined}>{value}</strong>
    </div>
  );
}

function sourceLabel(sourceTable?: string, sourceId?: string): string | undefined {
  if (!sourceTable && !sourceId) return undefined;
  if (!sourceId) return sourceTable;
  if (!sourceTable) return sourceId;
  return `${sourceTable} · ${sourceId}`;
}

function formatConfidence(value: number | undefined): string | undefined {
  return typeof value === 'number' ? value.toFixed(2) : undefined;
}

function formatValidity(validFrom?: string, validUntil?: string): string | undefined {
  if (!validFrom && !validUntil) return 'active until changed';
  if (validFrom && validUntil) return `${formatCompactDate(validFrom)} → ${formatCompactDate(validUntil)}`;
  if (validFrom) return `from ${formatCompactDate(validFrom)}`;
  return `until ${formatCompactDate(validUntil)}`;
}

function formatCompactDate(value?: string): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
