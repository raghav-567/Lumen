'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import {
  Activity, FileText, Bell, AlertTriangle,
  TrendingUp, Shield, Zap, CheckCircle2, ChevronRight
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
    if (score >= 60) return '#ef4444'; // severity-critical
    if (score >= 30) return '#f59e0b'; // severity-high
    if (score >= 10) return '#3b82f6'; // severity-medium
    return '#10b981'; // accent-emerald
  };

  const getDriftGradient = (score: number) => {
    if (score >= 60) return 'linear-gradient(90deg, #ef4444 0%, #b91c1c 100%)';
    if (score >= 30) return 'linear-gradient(90deg, #f59e0b 0%, #d97706 100%)';
    if (score >= 10) return 'linear-gradient(90deg, #3b82f6 0%, #1d4ed8 100%)';
    return 'linear-gradient(90deg, #10b981 0%, #047857 100%)';
  };

  if (loading) {
    return (
      <div className="fade-in" style={{ padding: '2rem' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '24px' }}>
          {[1, 2, 3, 4].map((i) => <div key={i} className="skeleton" style={{ height: 140, borderRadius: 20 }} />)}
        </div>
      </div>
    );
  }

  return (
    <div className="fade-in" style={{ paddingBottom: '40px' }}>
      
      {/* ── Premium Hero Section ── */}
      <div style={{
        position: 'relative',
        padding: '40px 48px',
        borderRadius: '24px',
        marginBottom: '40px',
        overflow: 'hidden',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        background: 'linear-gradient(135deg, rgba(124, 92, 252, 0.08) 0%, rgba(79, 143, 255, 0.03) 100%)',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.2)',
      }}>
        {/* Glow meshes behind hero */}
        <div style={{
          position: 'absolute', top: '-50%', right: '-10%', width: '400px', height: '400px',
          background: 'var(--accent-indigo)', filter: 'blur(100px)', opacity: 0.15, borderRadius: '50%', pointerEvents: 'none'
        }} />
        <div style={{
          position: 'absolute', bottom: '-50%', left: '10%', width: '300px', height: '300px',
          background: 'var(--accent-blue)', filter: 'blur(100px)', opacity: 0.1, borderRadius: '50%', pointerEvents: 'none'
        }} />
        
        <div style={{ position: 'relative', zIndex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
            <div style={{ 
              background: 'linear-gradient(135deg, var(--accent-indigo), var(--accent-blue))',
              borderRadius: '12px', padding: '8px', display: 'flex', color: 'white', boxShadow: '0 4px 12px rgba(124,92,252,0.3)'
            }}>
              <Activity size={24} />
            </div>
            <h1 style={{ fontSize: '2rem', fontWeight: 800, letterSpacing: '-0.02em', background: 'linear-gradient(to right, #fff, #a0a0b8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              System Overview
            </h1>
          </div>
          <p style={{ fontSize: '1rem', color: 'var(--text-secondary)', maxWidth: '600px', lineHeight: 1.5 }}>
            Real-time analysis of your knowledge base. Monitoring content health, detecting contradictions, and measuring semantic drift.
          </p>
        </div>
      </div>

      {/* ── Glassmorphic Stat Cards ── */}
      <div style={{ 
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '20px', marginBottom: '48px' 
      }}>
        <StatCard 
          icon={<FileText size={22} />} 
          title="Indexed Documents" 
          value={docCount} 
          color="var(--accent-blue)"
          trend="+12% this week"
        />
        <StatCard 
          icon={<Bell size={22} />} 
          title="Open Alerts" 
          value={alertStats?.open || 0} 
          color="var(--accent-indigo)"
          trend="Requires attention"
          highlight
        />
        <StatCard 
          icon={<AlertTriangle size={22} />} 
          title="Critical Anomalies" 
          value={alertStats?.critical || 0} 
          color="var(--severity-critical)"
          trend="Immediate action needed"
        />
        <StatCard 
          icon={<TrendingUp size={22} />} 
          title="Avg System Drift" 
          value={`${avgDrift.toFixed(1)}%`} 
          color={getDriftColor(avgDrift)}
          trend="Across all collections"
        />
      </div>

      {/* ── Top Drift Risks (Sleek List) ── */}
      <div style={{
        background: 'rgba(255, 255, 255, 0.02)',
        backdropFilter: 'blur(12px)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: '24px',
        padding: '32px',
        boxShadow: '0 16px 40px -8px rgba(0,0,0,0.3)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '28px' }}>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Shield size={22} style={{ color: 'var(--accent-indigo)' }} /> Priority Risks
          </h2>
          <button style={{ 
            background: 'transparent', border: 'none', color: 'var(--accent-blue)', 
            fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' 
          }}>
            View All <ChevronRight size={16} />
          </button>
        </div>

        {driftScores.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)' }}>
            <CheckCircle2 size={40} style={{ margin: '0 auto 16px', opacity: 0.2 }} />
            <p>Knowledge base is fully healthy.</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {driftScores.slice(0, 10).map((d, idx) => (
              <div 
                key={d.document_id} 
                className="hover-card"
                style={{ 
                  animation: `fadeInUp 500ms ease-out ${idx * 60}ms both`,
                  background: 'rgba(255, 255, 255, 0.015)',
                  border: '1px solid rgba(255, 255, 255, 0.04)',
                  borderRadius: '16px',
                  padding: '20px 24px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '24px',
                  position: 'relative',
                  overflow: 'hidden',
                  transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                  cursor: 'pointer'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(255, 255, 255, 0.04)';
                  e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.1)';
                  e.currentTarget.style.transform = 'translateY(-2px) scale(1.005)';
                  e.currentTarget.style.boxShadow = '0 12px 24px -10px rgba(0,0,0,0.5)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'rgba(255, 255, 255, 0.015)';
                  e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.04)';
                  e.currentTarget.style.transform = 'translateY(0) scale(1)';
                  e.currentTarget.style.boxShadow = 'none';
                }}
              >
                {/* Left side: details */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <h3 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)' }}>{d.title}</h3>
                    {d.drift_type === 'both' && (
                      <span style={{ fontSize: '0.65rem', padding: '2px 8px', borderRadius: '100px', background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Critical Alert</span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'flex', gap: '16px' }}>
                    <span>Type: <span style={{ color: 'var(--text-secondary)' }}>{d.drift_type || 'None'}</span></span>
                    <span>Document ID: <span style={{ fontFamily: 'monospace', opacity: 0.7 }}>{d.document_id.split('-')[0]}...</span></span>
                  </div>
                </div>

                {/* Right side: visual metrics */}
                <div style={{ width: '40%', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  
                  {/* Factual Bar */}
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '6px', fontWeight: 500 }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Inconsistency</span>
                      <span style={{ color: getDriftColor(d.factual_drift_score) }}>{d.factual_drift_score?.toFixed(1)}</span>
                    </div>
                    <div style={{ height: '6px', background: 'rgba(0,0,0,0.3)', borderRadius: '10px', overflow: 'hidden' }}>
                      <div style={{ 
                        height: '100%', 
                        width: `${Math.min(d.factual_drift_score || 0, 100)}%`, 
                        background: getDriftGradient(d.factual_drift_score),
                        boxShadow: `0 0 10px ${getDriftColor(d.factual_drift_score)}80`,
                        transition: 'width 1s cubic-bezier(0.4, 0, 0.2, 1)'
                      }} />
                    </div>
                  </div>

                  {/* Semantic Bar */}
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '6px', fontWeight: 500 }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Semantic Shift</span>
                      <span style={{ color: getDriftColor(d.semantic_drift_score) }}>{d.semantic_drift_score?.toFixed(1)}</span>
                    </div>
                    <div style={{ height: '6px', background: 'rgba(0,0,0,0.3)', borderRadius: '10px', overflow: 'hidden' }}>
                      <div style={{ 
                        height: '100%', 
                        width: `${Math.min(d.semantic_drift_score || 0, 100)}%`, 
                        background: getDriftGradient(d.semantic_drift_score),
                        boxShadow: `0 0 10px ${getDriftColor(d.semantic_drift_score)}80`,
                        transition: 'width 1s cubic-bezier(0.4, 0, 0.2, 1)'
                      }} />
                    </div>
                  </div>
                </div>

                {/* Overall Score Badge */}
                <div style={{ 
                  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', 
                  width: '64px', height: '64px', borderRadius: '50%',
                  background: `rgba(${d.drift_score >= 60 ? '239,68,68' : d.drift_score >= 30 ? '245,158,11' : '59,130,246'}, 0.1)`,
                  border: `2px solid ${getDriftColor(d.drift_score)}`,
                  marginLeft: '8px'
                }}>
                  <span style={{ fontSize: '1.2rem', fontWeight: 800, color: getDriftColor(d.drift_score), lineHeight: 1 }}>
                    {Math.round(d.drift_score)}
                  </span>
                  <span style={{ fontSize: '0.5rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 700, marginTop: '2px' }}>Score</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

    </div>
  );
}

function StatCard({ icon, title, value, color, trend, highlight = false }: any) {
  return (
    <div 
      style={{
        background: 'rgba(255, 255, 255, 0.02)',
        backdropFilter: 'blur(10px)',
        border: '1px solid rgba(255, 255, 255, 0.06)',
        borderRadius: '20px',
        padding: '24px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        position: 'relative',
        overflow: 'hidden',
        transition: 'all 0.3s ease',
        cursor: 'default',
        boxShadow: highlight ? `0 8px 32px -10px ${color}40` : '0 4px 20px -10px rgba(0,0,0,0.5)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = 'translateY(-4px)';
        e.currentTarget.style.borderColor = highlight ? color : 'rgba(255, 255, 255, 0.15)';
        e.currentTarget.style.boxShadow = `0 12px 40px -12px ${color}60`;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'translateY(0)';
        e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.06)';
        e.currentTarget.style.boxShadow = highlight ? `0 8px 32px -10px ${color}40` : '0 4px 20px -10px rgba(0,0,0,0.5)';
      }}
    >
      {/* Top right subtle glow */}
      <div style={{
        position: 'absolute', top: '-10px', right: '-10px', width: '80px', height: '80px',
        background: color, filter: 'blur(40px)', opacity: highlight ? 0.3 : 0.15, pointerEvents: 'none', borderRadius: '50%'
      }} />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ 
          width: '40px', height: '40px', borderRadius: '12px',
          background: `color-mix(in srgb, ${color} 15%, transparent)`,
          color: color, display: 'flex', alignItems: 'center', justifyContent: 'center'
        }}>
          {icon}
        </div>
        {highlight && (
          <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: color, boxShadow: `0 0 10px ${color}` }} />
        )}
      </div>

      <div>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 500, marginBottom: '4px' }}>
          {title}
        </div>
        <div style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1.1, letterSpacing: '-0.02em' }}>
          {value}
        </div>
        {trend && (
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ color: color }}>●</span> {trend}
          </div>
        )}
      </div>
    </div>
  );
}
