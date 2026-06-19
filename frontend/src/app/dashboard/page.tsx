'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { FileText, Bell, AlertTriangle, TrendingUp, CheckCircle2 } from 'lucide-react';

interface DriftScore {
  document_id: string;
  title: string;
  drift_score: number;
  semantic_drift_score: number;
  factual_drift_score: number;
  drift_type: string | null;
}

// Severity scale (DESIGN.md) — the only colour on the screen.
const SEV = { none: '#4A8C6F', low: '#B8A53D', medium: '#C8782E', high: '#C0392B' };
function driftColor(score: number) {
  if (score >= 60) return SEV.high;
  if (score >= 30) return SEV.medium;
  if (score >= 10) return SEV.low;
  return SEV.none;
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

  if (loading) {
    return (
      <div className="fade-in">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
          {[1, 2, 3, 4].map((i) => <div key={i} className="skeleton" style={{ height: 104, borderRadius: 16 }} />)}
        </div>
      </div>
    );
  }

  const criticalCount = alertStats?.critical || 0;

  return (
    <div className="fade-in">
      {/* Hero — editorial header, no colour */}
      <header style={{ marginBottom: 'var(--space-2xl)' }}>
        <h1 style={{ fontSize: '2.75rem', fontWeight: 600, letterSpacing: '-0.03em', lineHeight: 1.05 }}>
          Overview
        </h1>
        <p style={{ fontSize: '1.05rem', color: 'var(--text-secondary)', marginTop: 10, maxWidth: 560, lineHeight: 1.5 }}>
          The health of your knowledge base at a glance — where documents disagree, and how far they have drifted.
        </p>
      </header>

      {/* Stat row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16, marginBottom: 'var(--space-2xl)' }}>
        <StatCard icon={<FileText size={20} />} label="Indexed documents" value={docCount} />
        <StatCard icon={<Bell size={20} />} label="Open alerts" value={alertStats?.open || 0} />
        <StatCard
          icon={<AlertTriangle size={20} />}
          label="Critical anomalies"
          value={criticalCount}
          valueColor={criticalCount > 0 ? SEV.high : undefined}
        />
        <StatCard
          icon={<TrendingUp size={20} />}
          label="Average drift"
          value={avgDrift.toFixed(1)}
          valueColor={driftColor(avgDrift)}
        />
      </div>

      {/* Priority risks */}
      <section>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 'var(--space-lg)' }}>
          <h2 style={{ fontSize: '1.35rem', fontWeight: 600, letterSpacing: '-0.01em' }}>Priority risks</h2>
          <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
            Ranked by drift score
          </span>
        </div>

        {driftScores.length === 0 ? (
          <div className="empty-state" style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-sm)' }}>
            <CheckCircle2 size={40} style={{ color: SEV.none, opacity: 0.7 }} />
            <p style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>No drift detected. Your knowledge base is consistent.</p>
          </div>
        ) : (
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            {driftScores.slice(0, 10).map((d, idx) => (
              <DriftRow key={d.document_id} d={d} last={idx === Math.min(driftScores.length, 10) - 1} delay={idx * 50} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function StatCard({ icon, label, value, valueColor }: any) {
  return (
    <div className="stat-card">
      <div className="stat-icon">{icon}</div>
      <div>
        <div className="stat-value" style={valueColor ? { color: valueColor } : undefined}>{value}</div>
        <div className="stat-label">{label}</div>
      </div>
    </div>
  );
}

function MiniBar({ label, value }: { label: string; value: number }) {
  const v = Math.min(value || 0, 100);
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', marginBottom: 5 }}>
        <span style={{ color: 'var(--text-muted)' }}>{label}</span>
        <span className="num" style={{ color: driftColor(value), fontFamily: 'var(--font-mono)', fontWeight: 500 }}>
          {(value || 0).toFixed(1)}
        </span>
      </div>
      <div style={{ height: 4, background: 'var(--bg-subtle)', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${v}%`, background: driftColor(value), borderRadius: 4, transition: 'width 700ms ease-out' }} />
      </div>
    </div>
  );
}

function DriftRow({ d, last, delay }: { d: DriftScore; last: boolean; delay: number }) {
  return (
    <div
      style={{
        animation: `fadeInUp 450ms ease-out ${delay}ms both`,
        borderBottom: last ? 'none' : '1px solid var(--border-subtle)',
        padding: '20px 24px',
        display: 'flex',
        alignItems: 'center',
        gap: 28,
        transition: 'background var(--transition-fast)',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-subtle)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <h3 style={{ fontSize: '0.98rem', fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {d.title}
          </h3>
          {d.drift_type === 'both' && (
            <span className="badge badge-critical">both</span>
          )}
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 4 }}>
          {d.drift_type ? `${d.drift_type} drift` : 'no drift'} · <span style={{ fontFamily: 'var(--font-mono)' }}>{d.document_id.split('-')[0]}</span>
        </div>
      </div>

      <div style={{ width: 280, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <MiniBar label="Factual" value={d.factual_drift_score} />
        <MiniBar label="Semantic" value={d.semantic_drift_score} />
      </div>

      <div style={{ textAlign: 'right', minWidth: 64 }}>
        <div className="drift-score" style={{ fontSize: '2rem', color: driftColor(d.drift_score) }}>
          {Math.round(d.drift_score)}
        </div>
        <div style={{ fontSize: '0.6rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginTop: 2 }}>
          drift
        </div>
      </div>
    </div>
  );
}
