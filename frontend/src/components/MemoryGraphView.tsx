import { useEffect, useMemo, useState } from 'react';
import { Maximize2, Minimize2 } from 'lucide-react';
import { api } from '../api/client';
import { useLiveData } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
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
type EdgeCategory = 'all' | 'change' | 'conflict' | 'evidence' | 'causal' | 'other';
type TimeFilter = 'all' | 'today' | 'week' | 'month';

const EDGE_CATEGORIES: { id: EdgeCategory; label: string; types?: string[] }[] = [
  { id: 'all', label: 'All' },
  { id: 'change', label: 'Change', types: ['SUPERSEDED_BY'] },
  { id: 'conflict', label: 'Conflict', types: ['CONTRADICTS'] },
  { id: 'evidence', label: 'Evidence', types: ['MENTIONS', 'DERIVED_FROM'] },
  { id: 'causal', label: 'Causal', types: ['CAUSED_BY', 'LEADS_TO'] },
  { id: 'other', label: 'Other' },
];

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
        sourceTable: maybeString(n.source_table),
        sourceId: maybeString(n.source_id),
        createdAt: maybeString(n.created_at),
        metadata: objectRecord(n.metadata),
      };
    }),
    links: edges.map((e) => ({
      id: String(e.id ?? `${e.source_node_id ?? e.source}-${e.target_node_id ?? e.target}-${e.edge_type ?? e.type}`),
      source: String(e.source_node_id ?? e.source),
      target: String(e.target_node_id ?? e.target),
      type: String(e.edge_type ?? ''),
      confidence: parseConfidence(e.confidence),
      status: String(e.status ?? (e.invalidated_at ? 'invalidated' : 'active')),
      sourceObservations: Array.isArray(e.source_observations)
        ? e.source_observations.map(String)
        : [],
      validFrom: maybeString(e.valid_from),
      validUntil: maybeString(e.valid_until),
      createdAt: maybeString(e.created_at),
      invalidatedAt: maybeString(e.invalidated_at),
      metadata: objectRecord(e.metadata),
    })),
  };
}

export default function MemoryGraphView() {
  const { memoryRefreshKey } = useApp();
  const [search, setSearch] = useState('');
  const [nodeTypeFilter, setNodeTypeFilter] = useState<string>('all');
  const [edgeTypeFilter, setEdgeTypeFilter] = useState<string>('all');
  const [edgeCategoryFilter, setEdgeCategoryFilter] = useState<EdgeCategory>('all');
  const [timeFilter, setTimeFilter] = useState<TimeFilter>('all');
  const [isExpanded, setIsExpanded] = useState(false);
  const [expandedGraphHeight, setExpandedGraphHeight] = useState(620);
  const { data, status } = useLiveData(
    () => api.memoryGraph({ limit: 150 }),
    [memoryRefreshKey],
  );
  const nodes = useMemo(() => (data?.nodes ?? []) as Row[], [data]);
  const edges = useMemo(() => (data?.edges ?? []) as Row[], [data]);
  const nodeTypes = useMemo(
    () => Array.from(new Set(nodes.map((node) => String(node.node_type ?? 'entity')))).sort(),
    [nodes],
  );
  const edgeTypes = useMemo(
    () => Array.from(new Set(edges.map((edge) => String(edge.edge_type ?? 'RELATED')))).sort(),
    [edges],
  );
  const searchEdgeNodeIds = useMemo(() => {
    if (!search.trim()) return new Set<string>();
    const ids = new Set<string>();
    for (const edge of edges) {
      if (!matchesSearch(edge, search)) continue;
      ids.add(String(edge.source_node_id ?? edge.source));
      ids.add(String(edge.target_node_id ?? edge.target));
    }
    return ids;
  }, [edges, search]);
  const filteredNodes = useMemo(
    () => nodes.filter((node) => {
      const matchesType = nodeTypeFilter === 'all'
        || String(node.node_type ?? 'entity') === nodeTypeFilter;
      const nodeId = String(node.id);
      const matchesQuery = matchesSearch(node, search) || searchEdgeNodeIds.has(nodeId);
      return matchesType && matchesQuery && matchesTime(node, timeFilter);
    }),
    [nodes, nodeTypeFilter, search, searchEdgeNodeIds, timeFilter],
  );
  const filteredEdges = useMemo(() => {
    const visibleIds = new Set(filteredNodes.map((node) => String(node.id)));
    return edges.filter((edge) => {
      const source = String(edge.source_node_id ?? edge.source);
      const target = String(edge.target_node_id ?? edge.target);
      const type = String(edge.edge_type ?? 'RELATED');
      return visibleIds.has(source)
        && visibleIds.has(target)
        && matchesEdgeCategory(type, edgeCategoryFilter)
        && (edgeTypeFilter === 'all' || type === edgeTypeFilter)
        && matchesSearch(edge, search)
        && matchesTime(edge, timeFilter);
    });
  }, [edges, filteredNodes, edgeCategoryFilter, edgeTypeFilter, search, timeFilter]);

  useEffect(() => {
    if (!isExpanded) return undefined;

    const resize = () => setExpandedGraphHeight(Math.max(420, window.innerHeight - 300));
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsExpanded(false);
    };
    resize();
    document.body.classList.add('graph-expanded-open');
    window.addEventListener('resize', resize);
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      document.body.classList.remove('graph-expanded-open');
      window.removeEventListener('resize', resize);
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [isExpanded]);

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
          <div className={`graph-workspace${isExpanded ? ' expanded' : ''}`}>
            <div className="graph-filter-panel">
              <div className="graph-filter-row">
                <label className="graph-search">
                  <span>Search graph</span>
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Find entity, edge, source ID, or relationship"
                  />
                </label>
                <div className="graph-quick-actions">
                  <button
                    type="button"
                    className="graph-expand-button"
                    onClick={() => setIsExpanded((value) => !value)}
                    aria-label={isExpanded ? 'Restore graph view' : 'Expand graph to full screen'}
                    aria-pressed={isExpanded}
                    title={isExpanded ? 'Restore graph view (Esc)' : 'Expand graph to full screen'}
                  >
                    {isExpanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
                    {isExpanded ? 'Restore' : 'Full screen'}
                  </button>
                  <button type="button" onClick={() => setEdgeCategoryFilter('conflict')}>
                    Show contradiction chain
                  </button>
                  <button type="button" onClick={() => setEdgeCategoryFilter('evidence')}>
                    Show evidence lineage
                  </button>
                </div>
              </div>
              <div className="graph-filter-group">
                <span>Nodes</span>
                <button
                  type="button"
                  className={nodeTypeFilter === 'all' ? 'active' : ''}
                  onClick={() => setNodeTypeFilter('all')}
                >
                  All
                </button>
                {nodeTypes.map((type) => (
                  <button
                    type="button"
                    key={type}
                    className={nodeTypeFilter === type ? 'active' : ''}
                    onClick={() => setNodeTypeFilter(type)}
                  >
                    {type.replace('_', ' ')}
                  </button>
                ))}
              </div>
              <div className="graph-filter-group">
                <span>Relationship groups</span>
                {EDGE_CATEGORIES.map((category) => (
                  <button
                    type="button"
                    key={category.id}
                    className={edgeCategoryFilter === category.id ? 'active' : ''}
                    onClick={() => {
                      setEdgeCategoryFilter(category.id);
                      setEdgeTypeFilter('all');
                    }}
                  >
                    {category.label}
                  </button>
                ))}
              </div>
              <div className="graph-filter-group">
                <span>Edge type</span>
                <button
                  type="button"
                  className={edgeTypeFilter === 'all' ? 'active' : ''}
                  onClick={() => setEdgeTypeFilter('all')}
                >
                  All
                </button>
                {edgeTypes.map((type) => (
                  <button
                    type="button"
                    key={type}
                    className={edgeTypeFilter === type ? 'active' : ''}
                    onClick={() => setEdgeTypeFilter(type)}
                  >
                    {type.replace('_', ' ')}
                  </button>
                ))}
              </div>
              <div className="graph-filter-group">
                <span>Time range</span>
                {[
                  ['all', 'All time'],
                  ['today', 'Today'],
                  ['week', '7 days'],
                  ['month', '30 days'],
                ].map(([value, label]) => (
                  <button
                    type="button"
                    key={value}
                    className={timeFilter === value ? 'active' : ''}
                    onClick={() => setTimeFilter(value as TimeFilter)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="graph-filter-count">
                Showing {filteredNodes.length} nodes · {filteredEdges.length} edges
              </div>
            </div>
            {filteredNodes.length === 0 ? (
              <ViewStatus
                status="live"
                emptyLabel="No graph records match this filter."
                hint="Broaden the node or edge filter to inspect more memory."
              />
            ) : (
              <GraphView
                height={isExpanded ? expandedGraphHeight : 460}
                data={toGraphData(filteredNodes, filteredEdges)}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}

function parseConfidence(value: unknown): number | undefined {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function maybeString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function objectRecord(value: unknown): Record<string, unknown> | undefined {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return undefined;
}

function matchesSearch(record: Row, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return JSON.stringify(record).toLowerCase().includes(needle);
}

function matchesTime(record: Row, filter: TimeFilter): boolean {
  if (filter === 'all') return true;
  const value = maybeString(record.created_at) ?? maybeString(record.valid_from);
  if (!value) return false;
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return false;
  const ageMs = Date.now() - timestamp;
  if (filter === 'today') return ageMs <= 24 * 60 * 60 * 1000;
  if (filter === 'week') return ageMs <= 7 * 24 * 60 * 60 * 1000;
  return ageMs <= 30 * 24 * 60 * 60 * 1000;
}

function matchesEdgeCategory(type: string, category: EdgeCategory): boolean {
  if (category === 'all') return true;
  const normalized = type.toUpperCase();
  const selected = EDGE_CATEGORIES.find((item) => item.id === category);
  if (selected?.types) return selected.types.includes(normalized);
  const known = new Set(
    EDGE_CATEGORIES.flatMap((item) => item.types ?? []),
  );
  return category === 'other' && !known.has(normalized);
}
