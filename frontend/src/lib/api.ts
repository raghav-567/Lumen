import { DEMO_DATA } from './demoData';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

// Demo mode: when NEXT_PUBLIC_DEMO_MODE=true the client serves bundled fixtures
// (a snapshot of the seeded demo org) instead of calling a backend, so the
// frontend is fully interactive when deployed standalone (e.g. on Vercel).
// Leave the flag unset for normal local development against the real API.
const DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

// A mutable per-session copy so in-demo edits (reviews, alerts, weights) are
// reflected in the UI for the session without a backend.
const demoState: any = DEMO ? JSON.parse(JSON.stringify(DEMO_DATA)) : null;

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function demo<T>(value: T, ms = 280): Promise<T> {
  await wait(ms);
  // return a fresh copy so callers can't mutate the fixtures by reference
  return JSON.parse(JSON.stringify(value)) as T;
}

class ApiClient {
  private token: string | null = null;

  constructor() {
    if (typeof window !== 'undefined') {
      this.token = localStorage.getItem('access_token');
    }
  }

  setToken(token: string) {
    this.token = token;
    if (typeof window !== 'undefined') {
      localStorage.setItem('access_token', token);
    }
  }

  clearToken() {
    this.token = null;
    if (typeof window !== 'undefined') {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    }
  }

  private async request<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    if (!(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }

    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    // A 401 on a normal request means an expired/invalid session — clear it and
    // bounce to login. But a 401 from the auth endpoints themselves is just bad
    // credentials: let it fall through so the login page can show the error
    // inline instead of hard-redirecting (which wiped the message).
    if (res.status === 401 && !path.startsWith('/auth/')) {
      this.clearToken();
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
      throw new Error('Unauthorized');
    }

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Request failed' }));
      const err: any = new Error(error.detail || error.message || `HTTP ${res.status}`);
      err.status = res.status;
      err.data = error;
      throw err;
    }

    if (res.status === 204) return {} as T;
    return res.json();
  }

  // ── Auth ─────────────────────────────────────────────

  async register(data: { email: string; password: string; full_name: string; org_name: string }) {
    if (DEMO) {
      this.setToken('demo-session');
      return demo({ access_token: 'demo-session', token_type: 'bearer' });
    }
    const res = await this.request<{ access_token: string; token_type: string }>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    this.setToken(res.access_token);
    return res;
  }

  async login(data: { email: string; password: string }) {
    if (DEMO) {
      // Any credentials sign in to the demo; the login page surfaces the
      // canonical demo credentials as a hint.
      this.setToken('demo-session');
      return demo({ access_token: 'demo-session', token_type: 'bearer' });
    }
    const res = await this.request<{ access_token: string; token_type: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    this.setToken(res.access_token);
    return res;
  }

  async getMe() {
    if (DEMO) return demo(demoState.me);
    return this.request<any>('/auth/me');
  }

  // ── Documents ────────────────────────────────────────

  async uploadDocument(file: File) {
    if (DEMO) {
      await wait(400);
      throw new Error('Document upload is disabled in the live demo (no backend). Explore the seeded documents instead.');
    }
    const formData = new FormData();
    formData.append('file', file);
    return this.request<any>('/documents/upload', {
      method: 'POST',
      body: formData,
    });
  }

  async listDocuments(skip = 0, limit = 50) {
    if (DEMO) {
      const docs = demoState.documents.documents.slice(skip, skip + limit);
      return demo({ documents: docs, total: demoState.documents.total });
    }
    return this.request<{ documents: any[]; total: number }>(`/documents?skip=${skip}&limit=${limit}`);
  }

  async getDocument(id: string) {
    if (DEMO) {
      const doc = demoState.documents.documents.find((d: any) => d.id === id) || demoState.documents.documents[0];
      return demo(doc);
    }
    return this.request<any>(`/documents/${id}`);
  }

  async deleteDocument(id: string) {
    if (DEMO) {
      demoState.documents.documents = demoState.documents.documents.filter((d: any) => d.id !== id);
      demoState.documents.total = demoState.documents.documents.length;
      return demo(undefined as unknown as void);
    }
    return this.request<void>(`/documents/${id}`, { method: 'DELETE' });
  }

  // ── Search ───────────────────────────────────────────

  async search(query: string, topK = 10) {
    if (DEMO) {
      return demo({ ...demoState.search, query, results: demoState.search.results.slice(0, topK) });
    }
    return this.request<{ results: any[]; query: string; total: number }>('/search', {
      method: 'POST',
      body: JSON.stringify({ query, top_k: topK }),
    });
  }

  // ── Alerts ───────────────────────────────────────────

  async listAlerts(params?: { status?: string; severity?: string; skip?: number; limit?: number }) {
    if (DEMO) {
      let items = demoState.alerts.alerts as any[];
      if (params?.status) items = items.filter((a) => a.status === params.status);
      if (params?.severity) items = items.filter((a) => a.severity === params.severity);
      return demo({ alerts: items, total: items.length });
    }
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.severity) qs.set('severity', params.severity);
    if (params?.skip) qs.set('skip', String(params.skip));
    if (params?.limit) qs.set('limit', String(params.limit));
    return this.request<{ alerts: any[]; total: number }>(`/alerts?${qs}`);
  }

  async getAlertStats() {
    if (DEMO) return demo(demoState.alertStats);
    return this.request<{ total: number; open: number; critical: number; high: number; resolved_today: number }>('/alerts/stats');
  }

  async updateAlert(id: string, status: string) {
    if (DEMO) {
      const a = demoState.alerts.alerts.find((x: any) => x.id === id);
      if (a) a.status = status;
      return demo(a || { id, status });
    }
    return this.request<any>(`/alerts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  }

  // ── Reviews ──────────────────────────────────────────

  async listReviews(params?: { review_status?: string; limit?: number; offset?: number }) {
    if (DEMO) {
      let items = demoState.reviews.items as any[];
      if (params?.review_status) {
        items = items.filter((r) => (r.review_status || 'PENDING') === params.review_status);
      }
      const offset = params?.offset ?? 0;
      const limit = params?.limit ?? 50;
      return demo({
        items: items.slice(offset, offset + limit),
        total: items.length,
        limit,
        offset,
      });
    }
    const qs = new URLSearchParams();
    if (params?.review_status) qs.set('review_status', params.review_status);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    return this.request<{ items: any[]; total: number; limit: number; offset: number }>(`/reviews?${qs}`);
  }

  async getReviewStats() {
    if (DEMO) return demo(demoState.reviewStats);
    return this.request<any>('/reviews/stats');
  }

  async submitReview(contradictionId: string, data: { review_status: string; review_reason?: string }) {
    if (DEMO) {
      const r = demoState.reviews.items.find((x: any) => x.id === contradictionId);
      const status = data.review_status.toUpperCase();
      if (r) {
        r.review_status = status;
        r.reviewed_at = new Date().toISOString();
        r.review_reason = data.review_reason || '';
      }
      return demo({
        id: contradictionId,
        review_status: status,
        reviewed_by: demoState.me.id,
        reviewed_at: new Date().toISOString(),
        review_reason: data.review_reason || '',
      });
    }
    return this.request<any>(`/reviews/${contradictionId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async getExplanation(contradictionId: string) {
    if (DEMO) {
      const r = demoState.reviews.items.find((x: any) => x.id === contradictionId);
      const a = r?.chunk_a_text ?? 'Claim A';
      const b = r?.chunk_b_text ?? 'Claim B';
      return demo({
        explanation: `These two statements set the same policy parameter to incompatible values: "${a}" versus "${b}". Both cannot hold simultaneously, so they are flagged as a direct contradiction.`,
        cached: false,
      });
    }
    return this.request<{ explanation: string; cached: boolean }>(`/reviews/${contradictionId}/explain`, {
      method: 'POST',
    });
  }

  // ── Drift & Graph ────────────────────────────────────

  async getDriftScores() {
    if (DEMO) return demo(demoState.drift);
    return this.request<{ scores: any[] }>('/drift/scores');
  }

  async triggerDriftScan() {
    if (DEMO) return demo({ status: 'scan_queued' });
    return this.request<any>('/drift/scan', { method: 'POST' });
  }

  async getGraphVisualization() {
    if (DEMO) return demo(demoState.graph);
    return this.request<{ nodes: any[]; links: any[] }>('/graph/visualize');
  }

  async getEntities() {
    if (DEMO) return demo(demoState.entities);
    return this.request<any[]>('/graph/entities');
  }

  // ── Admin (Changes 1, 3, 5, 6) ──────────────────────

  async getGateCalibration() {
    if (DEMO) return demo(demoState.gateCalibration);
    return this.request<{
      current_threshold: number;
      sample_rate: number;
      total_sampled_pairs: number;
      total_above_threshold_pairs: number;
      sampled_contradictions: number;
      sampled_contradiction_rate: number;
      sampled_similarity: { avg: number | null; min: number | null; max: number | null };
      above_threshold_similarity: { avg: number | null; min: number | null };
      recommendation: { action: string; suggested_threshold: number; reason: string };
    }>('/admin/gate-calibration');
  }

  async getLineageStats() {
    if (DEMO) return demo(demoState.lineageStats);
    return this.request<{
      total_inferred_evolutions: number;
      total_reviewed: number;
      overrides: number;
      confirmations: number;
      override_rate: number;
      overridden_signals: { avg_title_similarity: number | null; avg_date_gap_days: number | null };
      confirmed_signals: { avg_title_similarity: number | null; avg_date_gap_days: number | null };
      recommendation: string;
    }>('/admin/lineage-heuristic-stats');
  }

  async getTaskStatus(taskId: string) {
    if (DEMO) {
      return demo({
        task_id: taskId,
        status: 'SUCCESS',
        ready: true,
        successful: true,
        result: { detail: 'Demo mode — task results are illustrative.' },
        completed_at: new Date().toISOString(),
      });
    }
    return this.request<{
      task_id: string;
      status: string;
      ready: boolean;
      successful: boolean | null;
      result?: any;
      error?: string;
      traceback?: string;
      task_name?: string;
      completed_at?: string;
    }>(`/admin/tasks/${taskId}`);
  }

  async getDriftWeights() {
    if (DEMO) return demo(demoState.driftWeights);
    return this.request<{
      org_id: string;
      source: string;
      density_weight: number;
      confidence_weight: number;
      volume_weight: number;
      factual_weight: number;
      semantic_weight: number;
      updated_at?: string;
    }>('/admin/drift-weights');
  }

  async updateDriftWeights(weights: {
    density_weight: number;
    confidence_weight: number;
    volume_weight: number;
    factual_weight: number;
    semantic_weight: number;
  }) {
    if (DEMO) {
      demoState.driftWeights = {
        ...demoState.driftWeights,
        ...weights,
        source: 'custom',
        updated_at: new Date().toISOString(),
      };
      return demo({ ...weights, status: 'updated' });
    }
    return this.request<any>('/admin/drift-weights', {
      method: 'PUT',
      body: JSON.stringify(weights),
    });
  }
}

export const api = new ApiClient();
