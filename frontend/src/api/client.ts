const BASE_URL = (import.meta as any).env?.VITE_API_URL ?? 'http://localhost:8000';

export interface ChatRequest {
  message: string;
  session_id?: string;
  routing_strategy?: 'fast' | 'accurate';
}

export interface ChatResponse {
  answer: string;
  session_id: string;
  user_observation_id: string | null;
  assistant_observation_id: string | null;
  retrieval_mode: string;
  used_session_items: string[];
  used_memory_items: string[];
  trace_id: string | null;
}

export interface MemoryGraphResponse {
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
}

export interface ItemsResponse {
  items: Record<string, unknown>[];
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
  ready: boolean;
}

export const api = {
  githubAuthUrl: () => {
    const redirect = encodeURIComponent(window.location.origin);
    return `${BASE_URL}/auth/github/start?redirect=${redirect}`;
  },

  authMe: () => req<AuthResponse>('/auth/me'),

  startDemo: () => req<{ status: string; workspace_id: string; expires_at: string }>(
    '/auth/demo',
    { method: 'POST' },
  ),

  logout: () => req<void>('/auth/logout', { method: 'POST' }),

  health: () => req<{ status: string }>('/health'),

  chat: (body: ChatRequest) =>
    req<ChatResponse>('/chat', { method: 'POST', body: JSON.stringify(body) }),

  memoryGraph: (params?: { entity?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.entity) qs.set('entity', params.entity);
    if (params?.limit != null) qs.set('limit', String(params.limit));
    return req<MemoryGraphResponse>(`/memory/graph?${qs}`);
  },

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
};

export interface SessionSummary {
  session_id: string;
  title: string | null;
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
}

export interface AblationRow {
  name: string;
  disabled: string[];
  passed: number;
  total: number;
  pass_rate: number;
  lost: string[];
}

export interface EvaluationSummary {
  local_eval: {
    passed: number;
    total: number;
    pass_rate: number;
    cases: EvalCase[];
  } | null;
  ablation: {
    cases_path: string;
    run_slow_path: boolean;
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
