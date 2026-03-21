const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

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

    if (res.status === 401) {
      this.clearToken();
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
      throw new Error('Unauthorized');
    }

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Request failed' }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }

    if (res.status === 204) return {} as T;
    return res.json();
  }

  // ── Auth ─────────────────────────────────────────────

  async register(data: { email: string; password: string; full_name: string; org_name: string }) {
    const res = await this.request<{ access_token: string; refresh_token: string }>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    this.setToken(res.access_token);
    if (typeof window !== 'undefined') {
      localStorage.setItem('refresh_token', res.refresh_token);
    }
    return res;
  }

  async login(data: { email: string; password: string }) {
    const res = await this.request<{ access_token: string; refresh_token: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    this.setToken(res.access_token);
    if (typeof window !== 'undefined') {
      localStorage.setItem('refresh_token', res.refresh_token);
    }
    return res;
  }

  async getMe() {
    return this.request<any>('/auth/me');
  }

  // ── Documents ────────────────────────────────────────

  async uploadDocument(file: File) {
    const formData = new FormData();
    formData.append('file', file);
    return this.request<any>('/documents/upload', {
      method: 'POST',
      body: formData,
    });
  }

  async listDocuments(skip = 0, limit = 50) {
    return this.request<{ documents: any[]; total: number }>(`/documents?skip=${skip}&limit=${limit}`);
  }

  async getDocument(id: string) {
    return this.request<any>(`/documents/${id}`);
  }

  async deleteDocument(id: string) {
    return this.request<void>(`/documents/${id}`, { method: 'DELETE' });
  }

  // ── Search ───────────────────────────────────────────

  async search(query: string, topK = 10) {
    return this.request<{ results: any[]; query: string; total: number }>('/search', {
      method: 'POST',
      body: JSON.stringify({ query, top_k: topK }),
    });
  }

  // ── Alerts ───────────────────────────────────────────

  async listAlerts(params?: { status?: string; severity?: string; skip?: number; limit?: number }) {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.severity) qs.set('severity', params.severity);
    if (params?.skip) qs.set('skip', String(params.skip));
    if (params?.limit) qs.set('limit', String(params.limit));
    return this.request<{ alerts: any[]; total: number }>(`/alerts?${qs}`);
  }

  async getAlertStats() {
    return this.request<{ total: number; open: number; critical: number; high: number; resolved_today: number }>('/alerts/stats');
  }

  async updateAlert(id: string, status: string) {
    return this.request<any>(`/alerts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  }

  // ── Drift & Graph ────────────────────────────────────

  async getDriftScores() {
    return this.request<{ scores: any[] }>('/drift/scores');
  }

  async triggerDriftScan() {
    return this.request<any>('/drift/scan', { method: 'POST' });
  }

  async getGraphVisualization() {
    return this.request<{ nodes: any[]; links: any[] }>('/graph/visualize');
  }

  async getEntities() {
    return this.request<any[]>('/graph/entities');
  }
}

export const api = new ApiClient();
