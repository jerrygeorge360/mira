import { useMemo, useState } from 'react';
import { api } from '../api/client';
import { useLiveData } from '../api/useLiveData';
import { useApp } from '../context/AppContext';
import GraphView, { type GraphData } from './GraphView';
import { ViewStatus } from './ViewStatus';
import { Search } from 'lucide-react';
import { Eyebrow, Num, Stat, StatStrip, ViewHeader, ViewPage } from './view';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Field, FieldLabel } from '@/components/ui/field';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

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

  return (
    <ViewPage>
      <ViewHeader
        title="Memory Graph"
        description="Typed temporal topology. Click a node to inspect it, scroll to zoom, drag to pan."
      />
      {nodes.length === 0 ? (
        <ViewStatus
          status={status}
          emptyLabel="The memory graph is empty."
          hint="Chat with MIRA (or seed demo data) to populate entities, facts, and edges."
        />
      ) : (
        <>
          <StatStrip>
            <Stat label="Nodes" value={nodes.length} />
            <Stat label="Edges" value={edges.length} />
            <Stat label="Edge types" value={new Set(edges.map((e) => e.edge_type)).size} />
            <Stat label="Showing" value={<><Num value={filteredNodes.length} /> · <Num value={filteredEdges.length} /></>} detail="nodes · edges after filters" />
          </StatStrip>

          <Card>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-wrap items-end gap-3">
                <Field className="min-w-64 flex-1">
                  <FieldLabel htmlFor="graph-search">Search graph</FieldLabel>
                  <InputGroup>
                    <InputGroupAddon>
                      <Search />
                    </InputGroupAddon>
                    <InputGroupInput
                      id="graph-search"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Find entity, edge, source ID, or relationship"
                    />
                  </InputGroup>
                </Field>
                <Button variant="outline" onClick={() => setEdgeCategoryFilter('conflict')}>
                  Show contradiction chain
                </Button>
                <Button variant="outline" onClick={() => setEdgeCategoryFilter('evidence')}>
                  Show evidence lineage
                </Button>
              </div>

              <FilterRow
                label="Nodes"
                value={nodeTypeFilter}
                onChange={setNodeTypeFilter}
                options={[{ value: 'all', label: 'All' }, ...nodeTypes.map((type) => ({ value: type, label: type.replace('_', ' ') }))]}
              />
              <FilterRow
                label="Relationship groups"
                value={edgeCategoryFilter}
                onChange={(next) => {
                  setEdgeCategoryFilter(next as EdgeCategory);
                  setEdgeTypeFilter('all');
                }}
                options={EDGE_CATEGORIES.map((category) => ({ value: category.id, label: category.label }))}
              />
              <FilterRow
                label="Edge type"
                value={edgeTypeFilter}
                onChange={setEdgeTypeFilter}
                options={[{ value: 'all', label: 'All' }, ...edgeTypes.map((type) => ({ value: type, label: type.replace('_', ' ') }))]}
              />
              <FilterRow
                label="Time range"
                value={timeFilter}
                onChange={(next) => setTimeFilter(next as TimeFilter)}
                options={[
                  { value: 'all', label: 'All time' },
                  { value: 'today', label: 'Today' },
                  { value: 'week', label: '7 days' },
                  { value: 'month', label: '30 days' },
                ]}
              />
            </CardContent>
          </Card>

          {filteredNodes.length === 0 ? (
            <ViewStatus
              status="live"
              emptyLabel="No graph records match this filter."
              hint="Broaden the node or edge filter to inspect more memory."
            />
          ) : (
            <GraphView height={460} data={toGraphData(filteredNodes, filteredEdges)} />
          )}
        </>
      )}
    </ViewPage>
  );
}

/** One labelled row of mutually exclusive filter options. */
function FilterRow({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid items-center gap-x-4 gap-y-1.5 sm:grid-cols-[10rem_minmax(0,1fr)]">
      <Eyebrow>{label}</Eyebrow>
      <ToggleGroup
        variant="outline"
        size="sm"
        // separate buttons, not a joined bar: these rows wrap on narrow screens
        spacing={1}
        className="max-w-full flex-wrap"
        value={[value]}
        // pressing the selected option again keeps it selected: one is always active
        onValueChange={(next) => next[0] && onChange(next[0])}
        aria-label={label}
      >
        {options.map((option) => (
          <ToggleGroupItem key={option.value} value={option.value}>
            {option.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
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
