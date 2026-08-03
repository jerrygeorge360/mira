const BASE_URL = (import.meta as any).env?.VITE_API_URL ?? 'http://localhost:8000';

export interface ChatRequest {
  message: string;
  session_id?: string;
  routing_strategy?: 'fast' | 'hybrid' | 'accurate';
}

export interface ChatResponse {
  answer: string;
  session_id: string;
  user_observation_id: string | null;
  assistant_observation_id: string | null;
  retrieval_mode: string;
  used_session_items: string[];
  used_memory_items: string[];
  routing_decision?: Record<string, unknown> | null;
  trace_id: string | null;
  llm_usage?: LlmUsageSummary | null;
}

export interface LlmUsageSummary {
  run_id: string;
  calls: number;
  successful_calls: number;
  provider_measured_calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cached_input_tokens: number;
  reasoning_output_tokens: number;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
  gateway_input_tokens_original: number;
  gateway_input_tokens_compressed: number;
  gateway_tokens_saved: number;
  paritok_calls: number;
  gateway_measured_calls: number;
  gateway_savings_fully_measured: boolean;
  estimated_cost_usd: number;
  fully_measured: boolean;
}

export type ChatStreamEvent =
  | { type: 'stage'; stage: string; message: string }
  | { type: 'answer'; delta: string }
  | {
      type: 'trace';
      session_id: string;
      user_observation_id: string | null;
      assistant_observation_id: string | null;
      retrieval_mode: string;
      routing_decision?: Record<string, unknown> | null;
      used_session_items: string[];
      used_memory_items: string[];
      trace_id: string | null;
      llm_usage?: LlmUsageSummary | null;
    }
  | { type: 'complete'; session_id: string }
  | { type: 'cancelled'; message: string }
  | { type: 'error'; message: string };

export interface MemoryGraphResponse {
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
}

export interface ItemsResponse {
  items: Record<string, unknown>[];
}

export interface MemoryLifecycleResponse {
  items: Record<string, unknown>[];
}

export interface MemoryHealthResponse {
  health: Record<string, unknown>;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase();
  const headers = new Headers(init?.headers);
  if (init?.body) headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = readCookie('mira_csrf');
    if (csrf) headers.set('X-CSRF-Token', csrf);
  }
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers,
    credentials: 'include',
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function readCookie(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`;
  const match = document.cookie.split('; ').find((item) => item.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : null;
}

export interface AuthResponse {
  user: {
    id: string | null;
    github_login: string | null;
    display_name: string | null;
    avatar_url: string | null;
  };
  workspace: { id: string; name: string };
  auth_mode: 'github' | 'demo' | 'development';
  expires_at: string | null;
  is_platform_admin: boolean;
  ready: boolean;
}

export interface AdminOverviewResponse {
  generated_at: string;
  users: {
    registered: number;
    new_last_7_days: number;
    new_last_30_days: number;
    active_last_7_days: number;
  };
  workspaces: Record<string, number>;
  activity: {
    active_web_sessions: number;
    conversations: number;
    observations: number;
    retrieval_traces: number;
  };
  queue: Record<string, number>;
  oauth: {
    registered_clients: number;
    active_access_tokens: number;
  };
  registrations_last_30_days: Array<{ date: string; count: number }>;
}

export interface AdminProviderResponse {
  active: string | null;
  source: 'dashboard' | 'env' | 'default';
  model: string | null;
  gateway: 'direct' | 'paritok';
  gateway_source: 'explicit' | 'dashboard' | 'env' | 'default';
  gateways: Array<'direct' | 'paritok'>;
  paritok_upstream_profile: string | null;
  paritok_compatible: boolean;
  providers: Array<{
    name: string;
    model: string;
    endpoint: string;
    has_cloud_embeddings: boolean;
  }>;
}

export interface AdminLlmUsageResponse {
  generated_at: string;
  period_days: number;
  totals: {
    calls: number;
    successful_calls: number;
    provider_measured_calls: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_input_tokens: number;
    estimated_cost_usd: number;
    fully_measured: boolean;
  };
  by_gateway: Array<{
    name: string;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_input_tokens: number;
    average_latency_ms: number;
  }>;
  by_provider: Array<{
    name: string;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_input_tokens: number;
    average_latency_ms: number;
  }>;
  recent_calls: Array<Record<string, unknown>>;
}

export const api = {
  githubAuthUrl: () => {
    const redirect = encodeURIComponent(window.location.origin);
    return `${BASE_URL}/auth/github/start?redirect=${redirect}`;
  },

  authMe: () => req<AuthResponse>('/auth/me'),

  adminOverview: () => req<AdminOverviewResponse>('/admin/overview'),

  adminProvider: () => req<AdminProviderResponse>('/admin/provider'),

  adminLlmUsage: (days = 7) =>
    req<AdminLlmUsageResponse>(`/admin/llm-usage?days=${days}&limit=30`),

  updateAdminProvider: (profile: string) =>
    req<AdminProviderResponse>('/admin/provider', {
      method: 'PUT',
      body: JSON.stringify({ profile }),
    }),

  updateAdminGateway: (gateway: 'direct' | 'paritok') =>
    req<AdminProviderResponse>('/admin/gateway', {
      method: 'PUT',
      body: JSON.stringify({ gateway }),
    }),

  startDemo: () => req<{ status: string; workspace_id: string; expires_at: string }>(
    '/auth/demo',
    { method: 'POST' },
  ),

  logout: () => req<void>('/auth/logout', { method: 'POST' }),

  deleteWorkspaceData: () =>
    req<{ status: string; workspace_id: string; deleted: Record<string, number> }>(
      '/workspace/data',
      { method: 'DELETE' },
    ),

  health: () => req<{ status: string }>('/health'),

  chat: (body: ChatRequest) =>
    req<ChatResponse>('/chat', { method: 'POST', body: JSON.stringify(body) }),

  chatStream: (body: ChatRequest, onEvent: (event: ChatStreamEvent) => void, signal?: AbortSignal) =>
    streamReq('/chat/stream', body, onEvent, signal),

  memoryGraph: (params?: { entity?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.entity) qs.set('entity', params.entity);
    if (params?.limit != null) qs.set('limit', String(params.limit));
    return req<MemoryGraphResponse>(`/memory/graph?${qs}`);
  },

  memoryLifecycle: (params?: { session_id?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.session_id) qs.set('session_id', params.session_id);
    if (params?.limit != null) qs.set('limit', String(params.limit));
    return req<MemoryLifecycleResponse>(`/memory/lifecycle?${qs}`);
  },

  memoryHealth: () => req<MemoryHealthResponse>('/memory/health'),

  foresight: (params?: { status?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.limit != null) qs.set('limit', String(params.limit));
    return req<ItemsResponse>(`/foresight?${qs}`);
  },

  reflections: (params?: { limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.limit != null) qs.set('limit', String(params.limit));
    return req<ItemsResponse>(`/reflections?${qs}`);
  },

  communitySummaries: (params?: { limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.limit != null) qs.set('limit', String(params.limit));
    return req<ItemsResponse>(`/community-summaries?${qs}`);
  },

  session: (sessionId: string) => req<Record<string, unknown>>(`/sessions/${sessionId}`),

  sessionWorkingSet: (sessionId: string) =>
    req<Record<string, unknown>>(`/sessions/${sessionId}/working-set`),

  retrievalTrace: (traceId: string) =>
    req<Record<string, unknown>>(`/retrieval/traces/${traceId}`),

  evaluationSummary: () => req<EvaluationSummary>('/evaluation/summary'),

  sessions: (params?: { limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.limit != null) qs.set('limit', String(params.limit));
    return req<SessionListResponse>(`/sessions?${qs}`);
  },

  sessionMessages: (sessionId: string) =>
    req<SessionMessagesResponse>(`/sessions/${sessionId}/messages`),

  deleteSession: (sessionId: string) =>
    req<{ status: string; session_id: string; deleted: Record<string, number> }>(
      `/sessions/${encodeURIComponent(sessionId)}`,
      { method: 'DELETE' },
    ),

  updateSession: (sessionId: string, update: { title?: string; is_starred?: boolean }) =>
    req<{ session_id: string; title: string | null; is_starred: boolean }>(
      `/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(update),
      },
    ),
};

async function streamReq(
  path: string,
  body: unknown,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = new Headers({ 'Content-Type': 'application/json' });
  const csrf = readCookie('mira_csrf');
  if (csrf) headers.set('X-CSRF-Token', csrf);
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    body: JSON.stringify(body),
    headers,
    credentials: 'include',
    signal,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${detail}`);
  }
  if (!res.body) {
    throw new Error('API stream response did not include a readable body');
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      emitStreamLine(line, onEvent);
    }
  }
  buffer += decoder.decode();
  emitStreamLine(buffer, onEvent);
}

function emitStreamLine(line: string, onEvent: (event: ChatStreamEvent) => void) {
  const trimmed = line.trim();
  if (!trimmed) return;
  const decoded = JSON.parse(trimmed) as ChatStreamEvent;
  onEvent(decoded);
}

export interface SessionSummary {
  session_id: string;
  title: string | null;
  is_starred: boolean;
  user_id: string;
  status: string;
  created_at: string;
  updated_at: string | null;
  message_count: number;
}

export interface SessionListResponse {
  sessions: SessionSummary[];
}

export interface ChatMessage {
  role: string;
  content: string;
  created_at: string;
  retrieval_mode?: string | null;
  context_scope?: string | null;
  trace_id?: string | null;
}

export interface SessionMessagesResponse {
  session_id: string;
  messages: ChatMessage[];
}

export interface EvalCase {
  id: string;
  category: string;
  passed: boolean;
  retrieval_mode: string | null;
  score?: number | null;
  answer?: string | null;
  error?: string | null;
  checks?: Record<string, unknown>[];
  failed_checks?: Record<string, unknown>[];
  interactions?: Record<string, unknown>[];
  expect?: Record<string, unknown>;
}

export interface AblationRow {
  name: string;
  disabled: string[];
  applied?: string[];
  passed: number;
  total: number;
  pass_rate: number;
  drop_from_full?: number | null;
  lost: string[];
  results?: Record<string, unknown>[];
  note?: string | null;
}

export interface EvaluationSummary {
  local_eval: {
    passed: number;
    total: number;
    pass_rate: number;
    by_category?: Record<string, { passed: number; total: number }>;
    by_retrieval_mode?: Record<string, { passed: number; total: number }>;
    failed_cases?: EvalCase[];
    generated_at?: string | null;
    cases: EvalCase[];
  } | null;
  ablation: {
    cases_path: string;
    run_slow_path: boolean;
    llm_mode?: string | null;
    parallel?: number | null;
    rows: AblationRow[];
  } | null;
  benchmark: {
    suite: string;
    total_examples: number;
    llm_pass_rate: number;
    average_score: number;
    llm_mode: string;
    estimated_cost: number;
  } | null;
}
