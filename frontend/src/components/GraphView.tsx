import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { Minus, Plus, X } from 'lucide-react';
import { Eyebrow, KeyValue, KeyValueList } from './view';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
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
  const graphGroupRef = useRef<SVGGElement | null>(null);
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
    graphGroupRef.current = g.node();

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
      .attr('class', 'graph-node')
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
      graphGroupRef.current = null;
    };
  }, [height, data, labelMode]);

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const selectedNodeId = selectedNode?.id;
    const selectedEdgeId = selectedEdge?.id;
    const selectedEdgeSource = selectedEdge ? nodeId(selectedEdge.source) : null;
    const selectedEdgeTarget = selectedEdge ? nodeId(selectedEdge.target) : null;

    d3.select(el)
      .selectAll<SVGLineElement, Link>('line.graph-link-line')
      .classed('highlighted', d => {
        if (selectedEdgeId) return d.id === selectedEdgeId;
        if (selectedNodeId) return nodeId(d.source) === selectedNodeId || nodeId(d.target) === selectedNodeId;
        return false;
      })
      .classed('dimmed', d => {
        if (selectedEdgeId) return d.id !== selectedEdgeId;
        if (selectedNodeId) return nodeId(d.source) !== selectedNodeId && nodeId(d.target) !== selectedNodeId;
        return false;
      });

    d3.select(el)
      .selectAll<SVGCircleElement, Node>('circle.graph-node')
      .classed('highlighted', d => {
        if (selectedNodeId) return d.id === selectedNodeId;
        if (selectedEdgeId) return d.id === selectedEdgeSource || d.id === selectedEdgeTarget;
        return false;
      })
      .classed('dimmed', d => {
        if (selectedNodeId) return d.id !== selectedNodeId;
        if (selectedEdgeId) return d.id !== selectedEdgeSource && d.id !== selectedEdgeTarget;
        return false;
      });
  }, [selectedNode, selectedEdge]);

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

  function fitVisible() {
    const el = svgRef.current;
    const group = graphGroupRef.current;
    const zoom = zoomRef.current;
    if (!el || !group || !zoom) return;
    const box = group.getBBox();
    if (!box.width || !box.height) return;
    const width = el.clientWidth || 800;
    const scale = Math.max(0.2, Math.min(3, 0.88 / Math.max(box.width / width, box.height / height)));
    const x = (width - box.width * scale) / 2 - box.x * scale;
    const y = (height - box.height * scale) / 2 - box.y * scale;
    d3.select(el)
      .transition()
      .duration(220)
      .call(zoom.transform, d3.zoomIdentity.translate(x, y).scale(scale));
  }

  function fitSelection() {
    const el = svgRef.current;
    const zoom = zoomRef.current;
    if (!el || !zoom) return;
    const width = el.clientWidth || 800;
    const point = selectedNode
      ? { x: selectedNode.x ?? width / 2, y: selectedNode.y ?? height / 2 }
      : selectedEdge
        ? midpoint(selectedEdge)
        : null;
    if (!point) {
      fitVisible();
      return;
    }
    const scale = 1.8;
    const x = width / 2 - point.x * scale;
    const y = height / 2 - point.y * scale;
    d3.select(el)
      .transition()
      .duration(220)
      .call(zoom.transform, d3.zoomIdentity.translate(x, y).scale(scale));
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
    <div className="tw relative overflow-hidden rounded-xl border bg-card">
      <div
        className="absolute top-3 left-3 z-2 flex items-center gap-0.5 rounded-lg border bg-card/90 p-0.5 backdrop-blur"
        role="toolbar"
        aria-label="Graph controls"
      >
        <Button variant="ghost" size="icon-sm" onClick={() => zoomBy(1.25)} aria-label="Zoom in">
          <Plus />
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={() => zoomBy(0.8)} aria-label="Zoom out">
          <Minus />
        </Button>
        <Button variant="ghost" size="sm" onClick={fitVisible}>Fit</Button>
        <Button variant="ghost" size="sm" onClick={fitSelection}>Selection</Button>
        <Button variant="ghost" size="sm" onClick={resetZoom}>Reset</Button>
      </div>

      <ToggleGroup
        className="absolute top-3 right-3 z-2 max-w-[calc(100%-15rem)] overflow-x-auto rounded-md bg-card/90 backdrop-blur"
        variant="outline"
        size="sm"
        spacing={0}
        value={[labelMode]}
        onValueChange={(next) => next[0] && setLabelMode(next[0] as LabelMode)}
        aria-label="Graph label mode"
      >
        <ToggleGroupItem value="key">Key labels</ToggleGroupItem>
        <ToggleGroupItem value="entities">Entities</ToggleGroupItem>
        <ToggleGroupItem value="none">No labels</ToggleGroupItem>
      </ToggleGroup>

      <svg ref={svgRef} className="block w-full" style={{ height }} />

      {(selectedNode || selectedEdge) && (
        <Card
          size="sm"
          className="absolute top-14 right-3 z-3 max-h-[calc(100%-5rem)] w-[min(340px,calc(100%-1.5rem))] overflow-y-auto bg-card/95 backdrop-blur"
        >
          <CardHeader>
            <Eyebrow>{selectedNode ? selectedNode.type : `${relationshipCategory(selectedEdge?.type)} relationship`}</Eyebrow>
            <CardTitle className="wrap-break-word">
              {selectedNode ? selectedNode.name : selectedEdge?.type || 'RELATED'}
            </CardTitle>
            <CardDescription className="wrap-break-word">
              {selectedNode
                ? selectedNode.headline || selectedNode.sourceTable || 'Graph node'
                : `${nodeName(selectedEdge?.source)} → ${nodeName(selectedEdge?.target)}`}
            </CardDescription>
            <CardAction>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => {
                  setSelectedNode(null);
                  setSelectedEdge(null);
                }}
                aria-label="Close graph inspector"
              >
                <X />
              </Button>
            </CardAction>
          </CardHeader>

          <CardContent className="flex flex-col gap-3">
            {selectedNode && (
              <>
                <KeyValueList>
                  <InspectorField label="Source" value={sourceLabel(selectedNode.sourceTable, selectedNode.sourceId)} />
                  <InspectorField label="Created" value={formatCompactDate(selectedNode.createdAt)} />
                  <InspectorField label="Status" value={selectedNode.status || 'active'} />
                </KeyValueList>
                {selectedNode.summary && <p className="text-pretty text-muted-foreground">{selectedNode.summary}</p>}
                <Collapsible>
                  <CollapsibleTrigger render={<Button variant="ghost" size="xs" className="-ml-2" />}>
                    Advanced details
                  </CollapsibleTrigger>
                  <CollapsibleContent className="flex flex-col gap-2 pt-1">
                    <KeyValueList>
                      <InspectorField label="Node ID" value={selectedNode.id} />
                    </KeyValueList>
                    {selectedNode.metadata && <InspectorJson value={selectedNode.metadata} />}
                  </CollapsibleContent>
                </Collapsible>
              </>
            )}
            {selectedEdge && (
              <>
                <KeyValueList>
                  <InspectorField label="Status" value={selectedEdge.status || 'active'} />
                  <InspectorField label="Confidence" value={formatConfidence(selectedEdge.confidence)} />
                  <InspectorField label="Valid window" value={formatValidity(selectedEdge.validFrom, selectedEdge.validUntil)} />
                  <InspectorField label="Created" value={formatCompactDate(selectedEdge.createdAt)} />
                </KeyValueList>
                <p className="text-pretty text-muted-foreground">{relationshipDescription(selectedEdge.type)}</p>
                <Collapsible>
                  <CollapsibleTrigger render={<Button variant="ghost" size="xs" className="-ml-2" />}>
                    Advanced details
                  </CollapsibleTrigger>
                  <CollapsibleContent className="flex flex-col gap-2 pt-1">
                    <KeyValueList>
                      <InspectorField label="Edge ID" value={selectedEdge.id} />
                      <InspectorField label="Valid from" value={formatCompactDate(selectedEdge.validFrom)} />
                      <InspectorField label="Valid until" value={formatCompactDate(selectedEdge.validUntil)} />
                      <InspectorField label="Invalidated at" value={formatCompactDate(selectedEdge.invalidatedAt)} />
                      <InspectorField
                        label="Evidence"
                        value={selectedEdge.sourceObservations?.length ? selectedEdge.sourceObservations.join(', ') : undefined}
                      />
                    </KeyValueList>
                    {selectedEdge.metadata && <InspectorJson value={selectedEdge.metadata} />}
                  </CollapsibleContent>
                </Collapsible>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {/* legend: node types by colour, relationships by the same stroke the canvas draws */}
      <div className="pointer-events-none absolute bottom-3 left-3 flex flex-col gap-1.5 font-mono text-[11px] text-muted-foreground">
        <ul className="flex flex-wrap gap-x-3 gap-y-1">
          {Object.entries(TYPE_COLORS).map(([type, color]) => (
            <li key={type} className="flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: color }} aria-hidden="true" />
              {type.replace('_', ' ')}
            </li>
          ))}
        </ul>
        <ul className="flex flex-wrap gap-x-3 gap-y-1">
          {LEGEND_RELATIONSHIPS.map(([type, label]) => {
            const style = relationshipStyle(type);
            return (
              <li key={type} className="flex items-center gap-1.5">
                <svg width="22" height="6" aria-hidden="true">
                  <line x1="0" y1="3" x2="22" y2="3" stroke={style.color} strokeWidth={style.width} strokeDasharray={style.dash} />
                </svg>
                {label}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

const LEGEND_RELATIONSHIPS = [
  ['CONTRADICTS', 'contradicts'],
  ['SUPERSEDED_BY', 'superseded'],
  ['MENTIONS', 'mentions'],
  ['DERIVED_FROM', 'derived'],
] as const;

function nodeName(node: string | number | Node | undefined): string {
  if (node && typeof node === 'object' && 'name' in node) return node.name;
  return String(node ?? 'unknown');
}

function nodeId(node: string | number | Node | undefined): string {
  if (node && typeof node === 'object' && 'id' in node) return node.id;
  return String(node ?? '');
}

function midpoint(edge: Link): { x: number; y: number } {
  const source = edge.source as Node;
  const target = edge.target as Node;
  return {
    x: ((source.x ?? 0) + (target.x ?? 0)) / 2,
    y: ((source.y ?? 0) + (target.y ?? 0)) / 2,
  };
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

/** A label → value row that renders nothing when there is no value. */
function InspectorField({ label, value }: { label: string; value?: string | number | null }) {
  if (value === undefined || value === null || value === '') return null;
  return <KeyValue label={label}>{value}</KeyValue>;
}

function InspectorJson({ value }: { value: unknown }) {
  return (
    <pre className="max-h-48 overflow-auto rounded-lg border bg-background p-2 font-mono text-[11px] text-muted-foreground">
      {JSON.stringify(value, null, 2)}
    </pre>
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
