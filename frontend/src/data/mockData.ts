// Mock data mirroring ui/command_center_data.py

export const GRAPH_METRICS = [
  { label: 'Nodes', value: '1,284' },
  { label: 'Edges', value: '4,918' },
  { label: 'Integrity', value: '98%' },
];

export const CHAT_MESSAGES = [
  {
    role: 'user',
    content: 'Prepare me for the NovaDynamics meeting. What matters most?',
  },
  {
    role: 'assistant',
    content:
      'I pulled the freshest meeting context, the durable account pattern, and the active session constraints. The main thread is still enterprise AI adoption with security review risk.',
  },
];

export const BRIEF_DETAILS = [
  { label: 'Last meeting', value: 'Apr 28 · Strategy sync' },
  { label: 'Key focus', value: 'Enterprise AI rollout' },
  { label: 'Decision maker', value: 'Maya Chen, CTO' },
  { label: 'Current project', value: 'Pilot expansion' },
  { label: 'Concerns', value: 'Security, auditability, ROI' },
  { label: 'Sources', value: '27 memories' },
  { label: 'Confidence', value: '94%' },
];

export const SESSION_ITEMS = [
  { title: 'Use 2026 timeline for MIRA demo', type: 'Correction', priority: 'High', scope: 'Project' },
  { title: 'Benchmark cost cap should stay around $15', type: 'Decision', priority: 'High', scope: 'Cross-session' },
  { title: 'SQLite is source of truth; Chroma is index', type: 'Architecture', priority: 'High', scope: 'Project' },
  { title: 'Community summaries are not recursive summaries', type: 'Constraint', priority: 'Medium', scope: 'Project' },
  { title: 'Prepare polished judge narrative', type: 'Task', priority: 'Medium', scope: 'Current task' },
];

export const EVIDENCE_ITEMS = [
  { rank: '01', title: 'NovaDynamics Q2 meeting notes', source: 'Observation', score: '0.96' },
  { rank: '02', title: 'Enterprise AI rollout risks', source: 'Reflection', score: '0.91' },
  { rank: '03', title: 'Security review decision chain', source: 'Graph path', score: '0.88' },
  { rank: '04', title: 'Pilot expansion community summary', source: 'Community', score: '0.84' },
];

export const REFLECTIONS = [
  {
    time: '09:42',
    insight: 'Jerry favors research credibility when demo decisions affect the paper.',
    tags: ['Pattern', 'Strength'],
  },
  {
    time: 'Yesterday',
    insight: 'Cost controls matter most when live judge calls or benchmarks are involved.',
    tags: ['Balance', 'Growth'],
  },
  {
    time: 'Mon',
    insight: 'Architecture decisions should stay visible so contributors avoid wrong layers.',
    tags: ['Pattern'],
  },
];

export const COMMUNITIES = [
  { title: 'Product Strategy Trends', people: '14', insights: '38', delta: '+12%' },
  { title: 'AI in Enterprise', people: '22', insights: '61', delta: '+24%' },
  { title: 'Leadership & Management', people: '9', insights: '17', delta: '+7%' },
];

export const TIMELINE = [
  { when: 'Past', title: 'NovaDynamics Q2 Meeting', kind: 'Memory' },
  { when: 'Past', title: 'Product Strategy Workshop', kind: 'Event' },
  { when: 'Today', title: 'Security Review Completed', kind: 'Milestone' },
  { when: 'Today', title: 'Client Meeting NovaDynamics', kind: 'Task' },
  { when: 'Future', title: 'Phase 2 Launch', kind: 'Milestone' },
  { when: 'Future', title: 'Strategy Review Q2 Check-in', kind: 'Event' },
];

export const RESULT_ABSTRACT =
  'The local memory suite is ten cases spanning nine memory behaviors, each replaying real interactions through the live agent and scoring the mechanism, not just the answer text. It passes 10/10 on a live model (DeepSeek, real neural embeddings), and the harder cases are confirmed as physical artifacts in the graph — edges that exist and beliefs that close.';

export const RESULT_STATS = [
  { label: 'Live suite · DeepSeek', value: '10 / 10' },
  { label: 'Memory behaviors', value: '9 / 9' },
  { label: 'Contradiction reliability', value: '1/3 → 5/5' },
  { label: 'Embeddings', value: 'bge-small' },
];

export const RESULT_CATEGORIES = [
  { name: 'Direct fact recall', result: '1/1', checks: 'Recalls a stated fact via Quick retrieval.' },
  { name: 'Session correction', result: '1/1', checks: 'Applies an in-session correction before durable confirmation.' },
  { name: 'Cross-session recall', result: '1/1', checks: 'Continues a topic across a session boundary.' },
  { name: 'Contradiction handling', result: '1/1', checks: 'Separates unresolved conflicts from acknowledged changes.' },
  { name: 'Supersession', result: '1/1', checks: 'Closes the old fact and links the transition edge.' },
  { name: 'Foresight activation', result: '1/1', checks: 'Surfaces a future commitment when it matters.' },
  { name: 'Deep-mode synthesis', result: '1/1', checks: 'Routes identity / pattern questions to Deep retrieval.' },
  { name: 'Retrieval sufficiency', result: '1/1', checks: 'Abstains when memory is insufficient to answer.' },
  { name: 'Routing intent', result: '2/2', checks: 'Selects the right mode: direct, quick, deep, relational.' },
];

export const RESULT_EVIDENCE = [
  {
    title: 'Contradiction · belief revised',
    case: 'case 4',
    edge: 'SUPERSEDED_BY  I prefers_language Python  →  speaker prefers_language Rust',
    states: ['Python · superseded', 'Rust · active'],
  },
  {
    title: 'Supersession · transition split',
    case: 'case 5',
    edge: 'SUPERSEDED_BY  user uses MongoDB  →  user uses PostgreSQL',
    states: ['MongoDB · superseded', 'PostgreSQL · active', 'returned as graph_edge'],
  },
  {
    title: 'Foresight · task persisted',
    case: 'case 6',
    edge: 'foresight_records  "Hackathon submission due on 2026-07-17."',
    states: ['active', 'future task'],
  },
];

export const HISTORY_THREADS = [
  {
    id: 'nova',
    title: 'NovaDynamics meeting prep',
    subtitle: '27 memories · relational',
    messages: CHAT_MESSAGES,
  },
  {
    id: 'roadmap',
    title: 'Q3 roadmap trade-offs',
    subtitle: '12 memories · deep',
    messages: [
      { role: 'user', content: 'What are the biggest Q3 roadmap trade-offs?' },
      {
        role: 'assistant',
        content:
          'The main trade-off is demo polish versus backend depth. The graph, retrieval trace, and ablation story carry the strongest judge signal.',
      },
    ],
  },
  {
    id: 'benchmarks',
    title: 'Benchmark cost controls',
    subtitle: '8 memories · quick',
    messages: [
      { role: 'user', content: 'Keep the benchmark run credible but cheap.' },
      {
        role: 'assistant',
        content:
          'Use a small representative suite first: official benchmark tracks separate from ablations, with result slots marked pending until real runs.',
      },
    ],
  },
  {
    id: 'kelechi',
    title: 'Onboarding Kelechi',
    subtitle: '5 memories · session',
    messages: [
      { role: 'user', content: 'What should Kelechi own next?' },
      {
        role: 'assistant',
        content:
          'Kelechi should stay close to infra boundaries: queue reliability, worker runtime, CI, Docker, and repository contracts.',
      },
    ],
  },
];

export const GRAPH_DATA = {
  nodes: [
    { id: 'mira', name: 'MIRA', type: 'entity', val: 14, color: '#d97757', headline: 'Memory-Integrated Reasoning Architecture', summary: 'Central project entity tying observations, facts, graph edges, reflections, and retrieval behavior together.', status: 'High-confidence project context', evidence: ['obs_001', 'fact_arch_001'] },
    { id: 'you', name: 'You', type: 'entity', val: 11, color: '#d97757', headline: 'Primary user / project owner', summary: 'Used to connect preferences, corrections, assignments, and demo intent back to Jerry.', status: 'Active session identity', evidence: ['obs_002'] },
    { id: 'nova', name: 'NovaDynamics', type: 'entity', val: 9, color: '#d97757', headline: 'Demo customer context', summary: 'Example organization used to show meeting prep, retrieval traces, and source-backed synthesis.', status: 'Mock demo data', evidence: ['obs_010'] },
    { id: 'demo', name: 'Final demo', type: 'foresight', val: 8, color: '#e0a13a', headline: 'Future-relevant event', summary: 'Foresight record that should activate when demo preparation or deadlines become relevant.', status: 'Pending activation', evidence: ['foresight_001'] },
    { id: 'bench', name: 'Official benchmark', type: 'foresight', val: 8, color: '#e0a13a', headline: 'Evaluation milestone', summary: 'Tracks planned benchmark reporting separately from internal ablation studies.', status: 'Result pending', evidence: ['eval_plan_001'] },
    { id: 'judge', name: 'LLM-as-Judge', type: 'observation', val: 6, color: '#5b8def', headline: 'Evaluation method observation', summary: 'Represents judge-based scoring for synthesis quality and answer faithfulness.', status: 'Needs calibration', evidence: ['obs_024'] },
    { id: 'budget', name: 'Budget control', type: 'observation', val: 6, color: '#5b8def', headline: 'Prompt/context budget signal', summary: 'Connects context allocation, retrieval volume, and answer reliability.', status: 'Runtime constraint', evidence: ['obs_031'] },
    { id: 'refl1', name: 'Prefers credible eval', type: 'reflection', val: 7, color: '#9b7ad6', headline: 'Gated reflection', summary: 'Higher-order pattern: Jerry wants claims backed by benchmarks, ablations, and evidence.', status: 'Evidence-backed insight', evidence: ['reflection_004'] },
    { id: 'refl2', name: 'Cost-conscious', type: 'reflection', val: 7, color: '#9b7ad6', headline: 'Gated reflection', summary: 'Represents preference for useful memory without uncontrolled token or infrastructure cost.', status: 'Evidence-backed insight', evidence: ['reflection_006'] },
    { id: 'comm', name: 'Evaluation cluster', type: 'community', val: 10, color: '#3fb27f', headline: 'Community summary', summary: 'Cluster linking benchmarks, ablations, judge scoring, retrieval traces, and demo credibility.', status: 'Deep Mode context', evidence: ['community_eval_001'] },
    { id: 'kelechi', name: 'Kelechi', type: 'entity', val: 6, color: '#d97757', headline: 'Team member entity', summary: 'Used in ownership/review paths for infrastructure and database issues.', status: 'Collaborator context', evidence: ['entity_kelechi'] },
    { id: 'sqlite', name: 'SQLite source', type: 'atomic_fact', val: 5, color: '#8a8f99', headline: 'Atomic fact', summary: 'SQLite is treated as source of truth while vector stores remain indexes.', status: 'Accepted architecture decision', evidence: ['adr_0003'] },
  ],
  links: [
    { source: 'you', target: 'mira', type: 'WORKS_ON' },
    { source: 'you', target: 'nova', type: 'MENTIONS' },
    { source: 'nova', target: 'demo', type: 'LEADS_TO' },
    { source: 'demo', target: 'bench', type: 'LEADS_TO' },
    { source: 'bench', target: 'judge', type: 'EVALUATED_BY' },
    { source: 'bench', target: 'budget', type: 'CONSTRAINED_BY' },
    { source: 'judge', target: 'comm', type: 'PART_OF_COMMUNITY' },
    { source: 'budget', target: 'comm', type: 'PART_OF_COMMUNITY' },
    { source: 'comm', target: 'refl1', type: 'DERIVED_FROM' },
    { source: 'comm', target: 'refl2', type: 'DERIVED_FROM' },
    { source: 'refl1', target: 'you', type: 'DESCRIBES' },
    { source: 'mira', target: 'kelechi', type: 'OWNED_WITH' },
    { source: 'mira', target: 'sqlite', type: 'HAS_FACT' },
    { source: 'nova', target: 'comm', type: 'PART_OF_COMMUNITY' },
  ],
};
