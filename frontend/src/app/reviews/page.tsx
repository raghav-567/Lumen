'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import {
  Scale, ChevronDown, Check, X, Flag, Shuffle,
  GitBranch, AlertTriangle, RefreshCw, Loader2,
  Eye, Sparkles, Beaker,
} from 'lucide-react';

interface ReviewItem {
  id: string;
  chunk_a_text: string;
  chunk_b_text: string;
  doc_a_title: string;
  doc_b_title: string;
  classification: string;
  confidence: number;
  explanation: string | null;
  review_status: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_reason: string | null;
  is_temporal_evolution: boolean;
  inferred_lineage: boolean;
  explanation_valid: boolean;
  sampled: boolean;
  gate_similarity: number | null;
  created_at: string;
}

interface ReviewStats {
  total_pairs: number;
  reviewed: number;
  pending: number;
  approved: number;
  rejected: number;
  false_positive: number;
  intentional_divergence: number;
  temporal_evolutions: number;
  review_rate: number;
}

const statusFilters = [
  { value: '', label: 'All' },
  { value: 'PENDING', label: 'Pending' },
  { value: 'APPROVED', label: 'Approved' },
  { value: 'REJECTED', label: 'Rejected' },
  { value: 'FALSE_POSITIVE', label: 'False Positive' },
  { value: 'INTENTIONAL_DIVERGENCE', label: 'Divergence' },
];

export default function ReviewsPage() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [explanationLoading, setExplanationLoading] = useState<string | null>(null);

  const loadData = async () => {
    try {
      const [reviewData, statsData] = await Promise.all([
        api.listReviews({ review_status: filter || undefined, limit: 50 }),
        api.getReviewStats(),
      ]);
      setItems(reviewData.items);
      setTotal(reviewData.total);
      setStats(statsData);
    } catch (err) {
      console.error('Failed to load reviews:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, [filter]);

  const handleReview = async (id: string, status: string, reason?: string) => {
    setReviewing(id);
    try {
      await api.submitReview(id, { review_status: status, review_reason: reason });
      await loadData();
    } catch (err: any) {
      alert(`Review failed: ${err.message}`);
    } finally {
      setReviewing(null);
    }
  };

  const handleExplain = async (id: string) => {
    setExplanationLoading(id);
    try {
      const result = await api.getExplanation(id);
      setItems(prev => prev.map(item =>
        item.id === id ? { ...item, explanation: result.explanation, explanation_valid: true } : item
      ));
    } catch (err: any) {
      alert(`Explanation failed: ${err.message}`);
    } finally {
      setExplanationLoading(null);
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
    <div className="fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title"><Scale size={24} /> Reviews</h1>
          {stats && (
            <p className="page-subtitle">
              {stats.total_pairs} pairs · {stats.pending} pending · {stats.approved} approved · {(stats.review_rate * 100).toFixed(0)}% reviewed
            </p>
          )}
        </div>
      </div>

      {/* Filter bar */}
      <div className="filter-bar">
        {statusFilters.map(f => (
          <button key={f.value} className={`filter-pill ${filter === f.value ? 'active' : ''}`}
            onClick={() => setFilter(f.value)}>
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 120, borderRadius: 16 }} />)}
        </div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <Scale />
          <p>No contradictions match your filter.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {items.map((item, idx) => (
            <div key={item.id} className="review-card" style={{ animationDelay: `${idx * 40}ms` }}>

              {/* Card header — two tiers: the contradiction, then quiet meta */}
              <div
                onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}
                style={{ display: 'flex', alignItems: 'center', gap: 16, cursor: 'pointer' }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontWeight: 600, fontSize: '0.95rem', marginBottom: 5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {item.doc_a_title} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>vs</span> {item.doc_b_title}
                  </p>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {item.classification || 'unknown'} · {timeAgo(item.created_at)} · {((item.confidence || 0) * 100).toFixed(0)}% confidence
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
                  <span className={`badge badge-${item.review_status?.toLowerCase()}`}>
                    {item.review_status}
                  </span>
                  <ChevronDown size={16} style={{
                    color: 'var(--text-muted)', transition: 'transform var(--transition-fast)',
                    transform: expandedId === item.id ? 'rotate(180deg)' : 'rotate(0)',
                  }} />
                </div>
              </div>

              {/* Expanded content */}
              {expandedId === item.id && (
                <div style={{ marginTop: 16, animation: 'fadeInUp 300ms ease-out' }}>

                  {/* Detection flags + signal (demoted from the header) */}
                  {(item.inferred_lineage || item.sampled || (!item.explanation_valid && item.explanation) || (item.is_temporal_evolution && !item.inferred_lineage) || item.gate_similarity != null) && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
                      {item.inferred_lineage && <span className="meta-badge inferred"><GitBranch size={10} /> Inferred</span>}
                      {item.sampled && <span className="meta-badge sampled"><Beaker size={10} /> Sampled</span>}
                      {!item.explanation_valid && item.explanation && <span className="meta-badge stale"><AlertTriangle size={10} /> Stale</span>}
                      {item.is_temporal_evolution && !item.inferred_lineage && <span className="meta-badge evolution"><Shuffle size={10} /> Evolution</span>}
                      {item.gate_similarity != null && (
                        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>similarity {item.gate_similarity.toFixed(3)}</span>
                      )}
                    </div>
                  )}

                  {/* Claim comparison */}
                  <div style={{
                    display: 'grid', gridTemplateColumns: '1fr auto 1fr',
                    gap: 'var(--space-md)', alignItems: 'stretch',
                  }}>
                    <div style={{
                      padding: 'var(--space-md)', borderRadius: 'var(--radius-md)',
                      background: 'rgba(var(--severity-critical-raw), 0.05)',
                      border: '1px solid rgba(var(--severity-critical-raw), 0.12)',
                    }}>
                      <p style={{ fontSize: '0.68rem', color: 'var(--severity-critical)', marginBottom: 6, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        Claim A · {item.doc_a_title}
                      </p>
                      <p style={{ fontSize: '0.82rem', lineHeight: 1.65, color: 'var(--text-secondary)' }}>{item.chunk_a_text}</p>
                    </div>
                    <div className="vs-divider" style={{ flexDirection: 'column' }}>
                      <span className="vs-badge">VS</span>
                    </div>
                    <div style={{
                      padding: 'var(--space-md)', borderRadius: 'var(--radius-md)',
                      background: 'rgba(var(--severity-high-raw), 0.05)',
                      border: '1px solid rgba(var(--severity-high-raw), 0.12)',
                    }}>
                      <p style={{ fontSize: '0.68rem', color: 'var(--severity-high)', marginBottom: 6, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        Claim B · {item.doc_b_title}
                      </p>
                      <p style={{ fontSize: '0.82rem', lineHeight: 1.65, color: 'var(--text-secondary)' }}>{item.chunk_b_text}</p>
                    </div>
                  </div>

                  {/* Explanation section */}
                  <div style={{ marginTop: 14 }}>
                    {item.explanation ? (
                      <div className="evidence-panel" style={{
                        borderColor: !item.explanation_valid ? 'rgba(var(--severity-high-raw), 0.2)' : undefined,
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <div className="evidence-label">
                            Explanation
                            {!item.explanation_valid && (
                              <span style={{ color: 'var(--severity-high)', marginLeft: 8, fontWeight: 400, textTransform: 'none', fontSize: '0.72rem' }}>
                                — context may have changed since this was generated
                              </span>
                            )}
                          </div>
                          {!item.explanation_valid && (
                            <button
                              className="btn btn-sm btn-secondary"
                              onClick={() => handleExplain(item.id)}
                              disabled={explanationLoading === item.id}
                              style={{ fontSize: '0.72rem' }}
                            >
                              {explanationLoading === item.id ? <Loader2 size={12} className="spin" /> : <RefreshCw size={12} />}
                              Regenerate
                            </button>
                          )}
                        </div>
                        <p className="evidence-text" style={{ marginTop: 8 }}>{item.explanation}</p>
                      </div>
                    ) : (
                      <button
                        className="btn btn-sm btn-secondary"
                        onClick={() => handleExplain(item.id)}
                        disabled={explanationLoading === item.id}
                      >
                        {explanationLoading === item.id ? (
                          <><Loader2 size={14} className="spin" /> Generating...</>
                        ) : (
                          <><Sparkles size={14} /> Generate Explanation</>
                        )}
                      </button>
                    )}
                  </div>

                  {/* Review actions */}
                  {item.review_status === 'PENDING' && (
                    <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
                      <button className="btn btn-sm btn-primary" onClick={() => handleReview(item.id, 'APPROVED')}
                        disabled={reviewing === item.id}>
                        <Check size={14} /> Approve
                      </button>
                      <button className="btn btn-sm btn-secondary" onClick={() => handleReview(item.id, 'REJECTED')}
                        disabled={reviewing === item.id} style={{ borderColor: 'rgba(var(--severity-critical-raw), 0.3)', color: 'var(--severity-critical)' }}>
                        <X size={14} /> Reject
                      </button>
                      <button className="btn btn-sm btn-secondary" onClick={() => handleReview(item.id, 'FALSE_POSITIVE')}
                        disabled={reviewing === item.id}>
                        <Flag size={14} /> False Positive
                      </button>
                      <button className="btn btn-sm btn-secondary" onClick={() => handleReview(item.id, 'INTENTIONAL_DIVERGENCE')}
                        disabled={reviewing === item.id}>
                        <Shuffle size={14} /> Intentional
                      </button>
                    </div>
                  )}

                  {item.reviewed_at && (
                    <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 10 }}>
                      Reviewed {timeAgo(item.reviewed_at)}
                      {item.review_reason && <> — {item.review_reason}</>}
                    </p>
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
