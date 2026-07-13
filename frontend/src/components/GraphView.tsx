import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { GRAPH_DATA } from '../data/mockData';

interface Node extends d3.SimulationNodeDatum {
  id: string;
  name: string;
  type: string;
  val: number;
  color: string;
  headline: string;
  summary: string;
  status: string;
}

interface Link extends d3.SimulationLinkDatum<Node> {
  type: string;
}

export interface GraphData {
  nodes: Node[];
  links: Link[];
}

interface Props {
  height?: number;
  data?: GraphData;
}

export default function GraphView({ height = 460, data }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [selected, setSelected] = useState<Node | null>(null);

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

    svg.call(
      d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.2, 4])
        .on('zoom', ev => g.attr('transform', ev.transform))
    );

    // links
    const link = g
      .append('g')
      .selectAll<SVGLineElement, Link>('line')
      .data(links)
      .join('line')
      .attr('stroke', 'var(--border-strong)')
      .attr('stroke-width', 1.5)
      .attr('stroke-opacity', 0.6);

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
      .on('click', (_ev, d) => setSelected(prev => (prev?.id === d.id ? null : d)))
      .call(
        d3.drag<SVGCircleElement, Node>()
          .on('start', (ev, d) => { if (!ev.active) sim.alphaTarget(0.25).restart(); d.fx = d.x; d.fy = d.y; })
          .on('drag', (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
          .on('end', (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    // labels
    const label = g
      .append('g')
      .selectAll<SVGTextElement, Node>('text')
      .data(nodes)
      .join('text')
      .text(d => d.name)
      .attr('text-anchor', 'middle')
      .attr('dy', '0.35em')
      .attr('font-size', 10)
      .attr('font-family', 'Inter, sans-serif')
      .attr('font-weight', 600)
      .attr('fill', 'var(--text)')
      .attr('pointer-events', 'none');

    sim.on('tick', () => {
      link
        .attr('x1', d => (d.source as Node).x ?? 0)
        .attr('y1', d => (d.source as Node).y ?? 0)
        .attr('x2', d => (d.target as Node).x ?? 0)
        .attr('y2', d => (d.target as Node).y ?? 0);
      node.attr('cx', d => d.x ?? 0).attr('cy', d => d.y ?? 0);
      label.attr('x', d => d.x ?? 0).attr('y', d => d.y ?? 0);
    });

    return () => { sim.stop(); };
  }, [height, data]);

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
      <svg ref={svgRef} className="graph-canvas" style={{ height }} />
      {selected && (
        <div style={{
          position: 'absolute',
          top: 14,
          right: 14,
          width: 'min(320px, calc(100% - 28px))',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 18,
          padding: 16,
          boxShadow: 'var(--shadow-lg)',
          backdropFilter: 'blur(12px)',
        }}>
          <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--accent)', marginBottom: 6 }}>
            {selected.type}
          </div>
          <div style={{ fontSize: 18, fontWeight: 850, letterSpacing: '-.02em', marginBottom: 4 }}>{selected.name}</div>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10, lineHeight: 1.5 }}>{selected.headline}</div>
          <div style={{ fontSize: 12, lineHeight: 1.55, marginBottom: 10 }}>{selected.summary}</div>
          <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700 }}>{selected.status}</div>
          <button
            onClick={() => setSelected(null)}
            style={{ position: 'absolute', top: 10, right: 12, background: 'none', border: 'none', color: 'var(--muted)', fontSize: 16, cursor: 'pointer' }}
          >✕</button>
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
    </div>
  );
}
