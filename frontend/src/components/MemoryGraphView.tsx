import { api } from '../api/client';
import { useLiveData } from '../api/useLiveData';
import GraphView, { type GraphData } from './GraphView';
import { ViewStatus } from './ViewStatus';

const TYPE_COLORS: Record<string, string> = {
  entity: '#d97757',
  observation: '#5b8def',
  reflection: '#9b7ad6',
  community: '#3fb27f',
  foresight: '#e0a13a',
  atomic_fact: '#8a8f99',
};

type Row = Record<string, unknown>;

function toGraphData(nodes: Row[], edges: Row[]): GraphData {
  return {
    nodes: nodes.map((n) => {
      const type = String(n.node_type ?? 'entity');
      return {
        id: String(n.id),
        name: String(n.label ?? n.source_id ?? n.id),
        type,
        val: 9,
        color: TYPE_COLORS[type] ?? '#8a8f99',
        headline: String(n.source_table ?? type),
        summary: '',
        status: '',
      };
    }),
    links: edges.map((e) => ({
      source: String(e.source_node_id ?? e.source),
      target: String(e.target_node_id ?? e.target),
      type: String(e.edge_type ?? ''),
    })),
  };
}

export default function MemoryGraphView() {
  const { data, status } = useLiveData(() => api.memoryGraph({ limit: 150 }), []);
  const nodes = (data?.nodes ?? []) as Row[];
  const edges = (data?.edges ?? []) as Row[];

  return (
    <div>
      <div className="view-header">
        <h2>Memory Graph</h2>
        <p>Typed temporal topology · click a node to inspect, scroll to zoom, drag to pan</p>
      </div>
      {nodes.length === 0 ? (
        <ViewStatus
          status={status}
          emptyLabel="The memory graph is empty."
          hint="Chat with MIRA (or seed demo data) to populate entities, facts, and edges."
        />
      ) : (
        <>
          <div className="metric-row">
            {[
              { label: 'Nodes', value: String(nodes.length) },
              { label: 'Edges', value: String(edges.length) },
              { label: 'Edge types', value: String(new Set(edges.map((e) => e.edge_type)).size) },
            ].map((m, i) => (
              <div key={i} className="metric-card">
                <div className="val">{m.value}</div>
                <div className="lbl">{m.label}</div>
              </div>
            ))}
          </div>
          <GraphView height={460} data={toGraphData(nodes, edges)} />
        </>
      )}
    </div>
  );
}
