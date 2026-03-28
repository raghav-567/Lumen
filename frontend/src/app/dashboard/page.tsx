'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import {
  Activity, FileText, Bell, AlertTriangle,
  TrendingUp, Shield, Zap,
} from 'lucide-react';

interface DriftScore {
  document_id: string;
  title: string;
  drift_score: number;
  semantic_drift_score: number;
  factual_drift_score: number;
  drift_type: string | null;
}

export default function DashboardPage() {
  const [driftScores, setDriftScores] = useState<DriftScore[]>([]);
  const [alertStats, setAlertStats] = useState<any>(null);
  const [docCount, setDocCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [drift, stats, docs] = await Promise.all([
          api.getDriftScores(),
          api.getAlertStats(),
          api.listDocuments(0, 1),
        ]);
        setDriftScores(drift.scores || []);
        setAlertStats(stats);
        setDocCount(docs.total);
      } catch (err) {
        console.error('Dashboard load error:', err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const avgDrift = driftScores.length
    ? driftScores.reduce((s, d) => s + d.drift_score, 0) / driftScores.length
    : 0;

  const getDriftColor = (score: number) => {
    if (score >= 60) return 'var(--severity-critical)';
    if (score >= 30) return 'var(--severity-high)';
    if (score >= 10) return 'var(--severity-medium)';
    return 'var(--accent-emerald)';
  };

  if (loading) {
    return (
      <div className="fade-in">
        <div className="page-header">
          <h1 className="page-title"><Activity size={24} /> Dashboard</h1>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
          {[1, 2, 3, 4].map((i) => <div key={i} className="skeleton" style={{ height: 120, borderRadius: 16 }} />)}
        </div>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1 className="page-title"><Activity size={24} /> Dashboard</h1>
        <p className="page-subtitle">Knowledge drift overview</p>
      </div>

      {/* Stat cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16, marginBottom: 32 }}>
        <div className="stat-card">
          <div className="stat-icon"><FileText /></div>
          <div><div className="stat-value">{docCount}</div><div className="stat-label">Documents</div></div>
        </div>
        <div className="stat-card">
          <div className="stat-icon"><Bell /></div>
          <div><div className="stat-value">{alertStats?.open || 0}</div><div className="stat-label">Open Alerts</div></div>
        </div>
        <div className="stat-card">
          <div className="stat-icon"><AlertTriangle /></div>
          <div><div className="stat-value">{alertStats?.critical || 0}</div><div className="stat-label">Critical</div></div>
        </div>
        <div className="stat-card">
          <div className="stat-icon"><TrendingUp /></div>
          <div><div className="stat-value">{avgDrift.toFixed(1)}</div><div className="stat-label">Avg Drift</div></div>
        </div>
      </div>

      {/* Top drift risks */}
      <div className="card">
        <h2 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: 20, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Shield size={18} /> Top Drift Risks
        </h2>
        {driftScores.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>No documents analyzed yet.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {driftScores.slice(0, 10).map((d, idx) => (
              <div key={d.document_id} style={{ animation: `fadeInUp 400ms ease-out ${idx * 60}ms both` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <span style={{ fontSize: '0.88rem', fontWeight: 500 }}>{d.title}</span>
                  <span style={{ fontSize: '0.78rem', color: getDriftColor(d.drift_score), fontWeight: 700 }}>
                    {d.drift_score.toFixed(1)}
                  </span>
                </div>
                {/* Factual drift bar */}
                <div style={{ marginBottom: 4 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: 2 }}>
                    <span>Inconsistency</span>
                    <span style={{ color: getDriftColor(d.factual_drift_score) }}>{(d.factual_drift_score || 0).toFixed(1)}</span>
                  </div>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${Math.min(d.factual_drift_score || 0, 100)}%`, background: getDriftColor(d.factual_drift_score) }} />
                  </div>
                </div>
                {/* Semantic drift bar */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: 2 }}>
                    <span>Semantic Shift</span>
                    <span style={{ color: getDriftColor(d.semantic_drift_score) }}>{(d.semantic_drift_score || 0).toFixed(1)}</span>
                  </div>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${Math.min(d.semantic_drift_score || 0, 100)}%`, background: getDriftColor(d.semantic_drift_score) }} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
