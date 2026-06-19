'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import {
  Bell, Check, CheckCircle2, XCircle, Eye, ChevronDown,
} from 'lucide-react';

interface Alert {
  id: string;
  alert_type: string;
  severity: string;
  title: string;
  description: string | null;
  evidence: any;
  status: string;
  created_at: string;
  source_doc_id: string | null;
  target_doc_id: string | null;
}

const filters = [
  { value: '', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'acknowledged', label: 'Acknowledged' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'dismissed', label: 'Dismissed' },
];

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadAlerts = async () => {
    try {
      const data = await api.listAlerts({ status: filter || undefined, limit: 100 });
      setAlerts(data.alerts);
      setTotal(data.total);
    } catch (err) {
      console.error('Failed to load alerts:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAlerts(); }, [filter]);

  const handleStatusChange = async (id: string, newStatus: string) => {
    try {
      await api.updateAlert(id, newStatus);
      await loadAlerts();
    } catch (err: any) {
      alert(`Update failed: ${err.message}`);
    }
  };

  const timeAgo = (dateStr: string) => {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  };

  return (
    <div className="fade-in list-page">
      <div className="page-header">
        <h1 className="page-title"><Bell size={24} /> Alerts</h1>
        <p className="page-subtitle">{total} alerts found</p>
      </div>

      {/* Filter pills */}
      <div className="filter-bar">
        {filters.map((f) => (
          <button
            key={f.value}
            className={`filter-pill ${filter === f.value ? 'active' : ''}`}
            onClick={() => setFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 90, borderRadius: 16 }} />)}
        </div>
      ) : alerts.length === 0 ? (
        <div className="empty-state">
          <CheckCircle2 />
          <p>No alerts match your filter.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {alerts.map((alert, idx) => (
            <div
              key={alert.id}
              className={`alert-card severity-${alert.severity}`}
              style={{ animationDelay: `${idx * 40}ms` }}
            >
              <div
                onClick={() => setExpandedId(expandedId === alert.id ? null : alert.id)}
                style={{ display: 'flex', alignItems: 'center', gap: 16, cursor: 'pointer' }}
              >
                {/* Severity is carried by the card's left border — no extra badge */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontWeight: 600, marginBottom: 5, fontSize: '0.95rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{alert.title}</p>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {alert.severity} · {alert.alert_type.replace(/_/g, ' ')} · {timeAgo(alert.created_at)}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
                  <span className={`badge badge-${alert.status}`}>{alert.status}</span>
                  <ChevronDown
                    size={16}
                    style={{
                      color: 'var(--text-muted)',
                      transition: 'transform var(--transition-fast)',
                      transform: expandedId === alert.id ? 'rotate(180deg)' : 'rotate(0)',
                    }}
                  />
                </div>
              </div>

              {expandedId === alert.id && (
                <div style={{ marginTop: 'var(--space-lg)', animation: 'fadeInUp 300ms ease-out' }}>
                  {alert.description && (
                    <div className="evidence-panel">
                      <div className="evidence-label">Explanation</div>
                      <p className="evidence-text">{alert.description}</p>
                    </div>
                  )}

                  {alert.evidence && (alert.evidence.claim_a || alert.evidence.claim_b) && (
                    <div className="evidence-panel" style={{ marginTop: 'var(--space-sm)' }}>
                      <div className="evidence-label">
                        Evidence · Confidence: {((alert.evidence.confidence || 0) * 100).toFixed(0)}%
                      </div>
                      <div style={{
                        display: 'grid', gridTemplateColumns: '1fr auto 1fr',
                        gap: 'var(--space-md)', marginTop: 'var(--space-md)',
                        alignItems: 'stretch',
                      }}>
                        <div style={{
                          padding: 'var(--space-md)', borderRadius: 'var(--radius-md)',
                          background: 'rgba(var(--severity-critical-raw), 0.06)',
                          border: '1px solid rgba(var(--severity-critical-raw), 0.15)',
                        }}>
                          <p style={{ fontSize: '0.72rem', color: 'var(--severity-critical)', marginBottom: 6, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                            Claim A
                          </p>
                          <p style={{ fontSize: '0.82rem', lineHeight: 1.6 }}>{alert.evidence.claim_a}</p>
                        </div>
                        <div className="vs-divider" style={{ flexDirection: 'column' }}>
                          <span className="vs-badge">VS</span>
                        </div>
                        <div style={{
                          padding: 'var(--space-md)', borderRadius: 'var(--radius-md)',
                          background: 'rgba(var(--severity-high-raw), 0.06)',
                          border: '1px solid rgba(var(--severity-high-raw), 0.15)',
                        }}>
                          <p style={{ fontSize: '0.72rem', color: 'var(--severity-high)', marginBottom: 6, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                            Claim B
                          </p>
                          <p style={{ fontSize: '0.82rem', lineHeight: 1.6 }}>{alert.evidence.claim_b}</p>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Action buttons */}
                  {alert.status === 'open' && (
                    <div style={{ display: 'flex', gap: 8, marginTop: 'var(--space-lg)' }}>
                      <button className="btn btn-sm btn-secondary" onClick={() => handleStatusChange(alert.id, 'acknowledged')}>
                        <Eye size={14} /> Acknowledge
                      </button>
                      <button className="btn btn-sm btn-primary" onClick={() => handleStatusChange(alert.id, 'resolved')}>
                        <Check size={14} /> Resolve
                      </button>
                      <button className="btn btn-sm btn-secondary" onClick={() => handleStatusChange(alert.id, 'dismissed')}>
                        <XCircle size={14} /> Dismiss
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
