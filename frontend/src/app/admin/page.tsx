'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import {
  Settings, Target, GitBranch, Sliders,
  Activity, RefreshCw, CheckCircle2, AlertTriangle,
  ArrowDown, ArrowUp, Minus, Search, Loader2,
} from 'lucide-react';

export default function AdminPage() {
  const [gateData, setGateData] = useState<any>(null);
  const [lineageData, setLineageData] = useState<any>(null);
  const [weights, setWeights] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [taskId, setTaskId] = useState('');
  const [taskStatus, setTaskStatus] = useState<any>(null);
  const [taskLoading, setTaskLoading] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Editable weight state
  const [editWeights, setEditWeights] = useState({
    density_weight: 0.45,
    confidence_weight: 0.35,
    volume_weight: 0.20,
    factual_weight: 0.60,
    semantic_weight: 0.40,
  });

  useEffect(() => {
    const load = async () => {
      try {
        const [gate, lineage, w] = await Promise.all([
          api.getGateCalibration().catch(() => null),
          api.getLineageStats().catch(() => null),
          api.getDriftWeights().catch(() => null),
        ]);
        setGateData(gate);
        setLineageData(lineage);
        setWeights(w);
        if (w) {
          setEditWeights({
            density_weight: w.density_weight,
            confidence_weight: w.confidence_weight,
            volume_weight: w.volume_weight,
            factual_weight: w.factual_weight,
            semantic_weight: w.semantic_weight,
          });
        }
      } catch (err) {
        console.error('Admin load error:', err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const handleSaveWeights = async () => {
    setSaving(true);
    setSaveSuccess(false);
    try {
      await api.updateDriftWeights(editWeights);
      // Persisting alone does not change any existing drift score — the scorer
      // reads these weights only on the next recalc. Trigger one so the new
      // weights are actually applied to the current documents.
      await api.triggerDriftScan();
      const w = await api.getDriftWeights();
      setWeights(w);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 4000);
    } catch (err: any) {
      alert(`Save failed: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleTaskLookup = async () => {
    if (!taskId.trim()) return;
    setTaskLoading(true);
    try {
      const status = await api.getTaskStatus(taskId.trim());
      setTaskStatus(status);
    } catch (err: any) {
      setTaskStatus({ task_id: taskId, status: 'NOT_FOUND', error: err.message });
    } finally {
      setTaskLoading(false);
    }
  };

  const getActionIcon = (action: string) => {
    if (action === 'LOWER_THRESHOLD') return <ArrowDown size={14} />;
    if (action === 'RAISE_THRESHOLD') return <ArrowUp size={14} />;
    return <Minus size={14} />;
  };

  const getActionColor = (action: string) => {
    if (action === 'LOWER_THRESHOLD') return 'var(--severity-high)';
    if (action === 'RAISE_THRESHOLD') return 'var(--accent-emerald)';
    return 'var(--text-muted)';
  };

  const getTaskStatusColor = (status: string) => {
    if (status === 'SUCCESS') return 'var(--accent-emerald)';
    if (status === 'FAILURE') return 'var(--severity-critical)';
    if (status === 'STARTED' || status === 'RETRY') return 'var(--severity-high)';
    return 'var(--text-muted)';
  };

  const subSignalSum = editWeights.density_weight + editWeights.confidence_weight + editWeights.volume_weight;
  const blendSum = editWeights.factual_weight + editWeights.semantic_weight;
  const subValid = Math.abs(subSignalSum - 1.0) <= 0.01;
  const blendValid = Math.abs(blendSum - 1.0) <= 0.01;

  if (loading) {
    return (
      <div className="fade-in" style={{ padding: '2rem' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {[1, 2, 3, 4].map(i => <div key={i} className="skeleton" style={{ height: 200, borderRadius: 20 }} />)}
        </div>
      </div>
    );
  }

  return (
    <div className="fade-in" style={{ paddingBottom: 40 }}>
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title"><Settings size={24} /> Admin Panel</h1>
          <p className="page-subtitle">Pipeline calibration, heuristic monitoring, and drift weight tuning</p>
        </div>
      </div>

      <div className="admin-grid">

        {/* ── Section 1: Gate Calibration ── */}
        <div className="admin-card">
          <div className="admin-card-header">
            <div className="admin-card-icon">
              <Target size={20} />
            </div>
            <div>
              <h2 className="admin-card-title">Similarity Gate Calibration</h2>
              <p className="admin-card-subtitle">Empirical threshold validation from sampled sub-threshold pairs</p>
            </div>
          </div>

          {gateData ? (
            <div className="admin-card-body">
              <div className="admin-metrics-row">
                <div className="admin-metric">
                  <span className="admin-metric-value">{gateData.current_threshold}</span>
                  <span className="admin-metric-label">Current Threshold</span>
                </div>
                <div className="admin-metric">
                  <span className="admin-metric-value">{(gateData.sample_rate * 100).toFixed(0)}%</span>
                  <span className="admin-metric-label">Sample Rate</span>
                </div>
                <div className="admin-metric">
                  <span className="admin-metric-value">{gateData.total_sampled_pairs}</span>
                  <span className="admin-metric-label">Sampled Pairs</span>
                </div>
                <div className="admin-metric">
                  <span className="admin-metric-value">{gateData.sampled_contradictions}</span>
                  <span className="admin-metric-label">Were Contradictions</span>
                </div>
              </div>

              {gateData.total_sampled_pairs > 0 && (
                <div className="admin-insight" style={{ marginTop: 16 }}>
                  <span className="admin-insight-rate" style={{ color: gateData.sampled_contradiction_rate > 0.15 ? 'var(--severity-critical)' : 'var(--accent-emerald)' }}>
                    {(gateData.sampled_contradiction_rate * 100).toFixed(1)}%
                  </span>
                  <span className="admin-insight-text">of below-threshold pairs were actual contradictions</span>
                </div>
              )}

              {gateData.recommendation && (
                <div className="admin-recommendation" style={{ borderColor: getActionColor(gateData.recommendation.action) }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {getActionIcon(gateData.recommendation.action)}
                    <span style={{ fontWeight: 600, color: getActionColor(gateData.recommendation.action) }}>
                      {gateData.recommendation.action.replace(/_/g, ' ')}
                    </span>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                      → {gateData.recommendation.suggested_threshold}
                    </span>
                  </div>
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 6 }}>
                    {gateData.recommendation.reason}
                  </p>
                </div>
              )}

              {gateData.sampled_similarity?.avg != null && (
                <div style={{ marginTop: 16, fontSize: '0.78rem', color: 'var(--text-muted)', display: 'flex', gap: 20 }}>
                  <span>Sampled Avg Sim: <strong style={{ color: 'var(--text-secondary)' }}>{gateData.sampled_similarity.avg.toFixed(3)}</strong></span>
                  <span>Min: <strong style={{ color: 'var(--text-secondary)' }}>{gateData.sampled_similarity.min?.toFixed(3)}</strong></span>
                  <span>Max: <strong style={{ color: 'var(--text-secondary)' }}>{gateData.sampled_similarity.max?.toFixed(3)}</strong></span>
                </div>
              )}
            </div>
          ) : (
            <div className="admin-empty">No sampled pairs available yet. Data accumulates as the pipeline processes documents.</div>
          )}
        </div>

        {/* ── Section 2: Lineage Heuristic Stats ── */}
        <div className="admin-card">
          <div className="admin-card-header">
            <div className="admin-card-icon">
              <GitBranch size={20} />
            </div>
            <div>
              <h2 className="admin-card-title">Lineage Heuristic Monitor</h2>
              <p className="admin-card-subtitle">Reviewer feedback on inferred temporal evolutions</p>
            </div>
          </div>

          {lineageData ? (
            <div className="admin-card-body">
              <div className="admin-metrics-row">
                <div className="admin-metric">
                  <span className="admin-metric-value">{lineageData.total_inferred_evolutions}</span>
                  <span className="admin-metric-label">Inferred Evolutions</span>
                </div>
                <div className="admin-metric">
                  <span className="admin-metric-value">{lineageData.total_reviewed}</span>
                  <span className="admin-metric-label">Reviewed</span>
                </div>
                <div className="admin-metric">
                  <span className="admin-metric-value" style={{ color: lineageData.override_rate > 0.3 ? 'var(--severity-critical)' : 'var(--accent-emerald)' }}>
                    {(lineageData.override_rate * 100).toFixed(1)}%
                  </span>
                  <span className="admin-metric-label">Override Rate</span>
                </div>
              </div>

              {lineageData.total_reviewed > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 16 }}>
                  <div className="admin-signal-box confirmed">
                    <div className="admin-signal-label"><CheckCircle2 size={12} /> Confirmed ({lineageData.confirmations})</div>
                    {lineageData.confirmed_signals?.avg_title_similarity != null && (
                      <div className="admin-signal-detail">Title Sim: {lineageData.confirmed_signals.avg_title_similarity.toFixed(3)}</div>
                    )}
                    {lineageData.confirmed_signals?.avg_date_gap_days != null && (
                      <div className="admin-signal-detail">Date Gap: {lineageData.confirmed_signals.avg_date_gap_days.toFixed(0)}d</div>
                    )}
                  </div>
                  <div className="admin-signal-box overridden">
                    <div className="admin-signal-label"><AlertTriangle size={12} /> Overridden ({lineageData.overrides})</div>
                    {lineageData.overridden_signals?.avg_title_similarity != null && (
                      <div className="admin-signal-detail">Title Sim: {lineageData.overridden_signals.avg_title_similarity.toFixed(3)}</div>
                    )}
                    {lineageData.overridden_signals?.avg_date_gap_days != null && (
                      <div className="admin-signal-detail">Date Gap: {lineageData.overridden_signals.avg_date_gap_days.toFixed(0)}d</div>
                    )}
                  </div>
                </div>
              )}

              {lineageData.recommendation && (
                <div className="admin-recommendation" style={{ marginTop: 16 }}>
                  <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{lineageData.recommendation}</p>
                </div>
              )}
            </div>
          ) : (
            <div className="admin-empty">No heuristic feedback recorded yet. Reviews of inferred lineage pairs will appear here.</div>
          )}
        </div>

        {/* ── Section 3: Drift Weights Editor ── */}
        <div className="admin-card">
          <div className="admin-card-header">
            <div className="admin-card-icon">
              <Sliders size={20} />
            </div>
            <div>
              <h2 className="admin-card-title">Drift Scoring Weights</h2>
              <p className="admin-card-subtitle">
                Per-org tuning of factual vs semantic drift balance
                {weights?.source === 'custom' && (
                  <span className="badge" style={{ marginLeft: 8 }}>Custom</span>
                )}
                {weights?.source === 'defaults' && (
                  <span className="badge" style={{ marginLeft: 8 }}>Defaults</span>
                )}
              </p>
            </div>
          </div>

          <div className="admin-card-body">
            <div className="weight-section">
              <div className="weight-section-header">
                <span>Factual Drift Sub-Signals</span>
                <span className={`weight-sum ${subValid ? 'valid' : 'invalid'}`}>
                  Σ = {subSignalSum.toFixed(2)}
                </span>
              </div>

              <WeightSlider
                label="Density Weight"
                description="How much contradiction density matters"
                value={editWeights.density_weight}
                onChange={(v) => setEditWeights(p => ({ ...p, density_weight: v }))}
              />
              <WeightSlider
                label="Confidence Weight"
                description="How much NLI confidence matters"
                value={editWeights.confidence_weight}
                onChange={(v) => setEditWeights(p => ({ ...p, confidence_weight: v }))}
              />
              <WeightSlider
                label="Volume Weight"
                description="How much contradiction count matters"
                value={editWeights.volume_weight}
                onChange={(v) => setEditWeights(p => ({ ...p, volume_weight: v }))}
              />
            </div>

            <div className="weight-section" style={{ marginTop: 20 }}>
              <div className="weight-section-header">
                <span>Combined Drift Blend</span>
                <span className={`weight-sum ${blendValid ? 'valid' : 'invalid'}`}>
                  Σ = {blendSum.toFixed(2)}
                </span>
              </div>

              {/* Factual + semantic must sum to 1.0, so the two sliders are
                  complementary — moving one sets the other automatically. */}
              <WeightSlider
                label="Factual Weight"
                description="Factual drift contribution to combined score"
                value={editWeights.factual_weight}
                onChange={(v) => setEditWeights(p => ({ ...p, factual_weight: v, semantic_weight: Math.round((1 - v) * 100) / 100 }))}
              />
              <WeightSlider
                label="Semantic Weight"
                description="Semantic drift contribution to combined score"
                value={editWeights.semantic_weight}
                onChange={(v) => setEditWeights(p => ({ ...p, semantic_weight: v, factual_weight: Math.round((1 - v) * 100) / 100 }))}
              />
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 20 }}>
              <button
                className="btn btn-primary"
                onClick={handleSaveWeights}
                disabled={saving || !subValid || !blendValid}
              >
                {saving ? <><Loader2 size={14} className="spin" /> Saving...</> : 'Save Weights'}
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => setEditWeights({
                  density_weight: 0.45, confidence_weight: 0.35, volume_weight: 0.20,
                  factual_weight: 0.60, semantic_weight: 0.40,
                })}
              >
                Reset to Defaults
              </button>
              {saveSuccess && (
                <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--accent-emerald)', fontSize: '0.82rem' }}>
                  <CheckCircle2 size={14} /> Saved — recalculating drift scores…
                </span>
              )}
              {!saving && !saveSuccess && (!subValid || !blendValid) && (
                <span style={{ color: 'var(--severity-high)', fontSize: '0.82rem' }}>
                  {!subValid
                    ? `Density + Confidence + Volume must sum to 1.00 (currently ${subSignalSum.toFixed(2)})`
                    : `Factual + Semantic must sum to 1.00 (currently ${blendSum.toFixed(2)})`}
                </span>
              )}
            </div>

            {weights?.updated_at && (
              <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 8 }}>
                Last updated: {new Date(weights.updated_at).toLocaleString()}
              </p>
            )}
          </div>
        </div>

        {/* ── Section 4: Task Status Monitor ── */}
        <div className="admin-card">
          <div className="admin-card-header">
            <div className="admin-card-icon">
              <Activity size={20} />
            </div>
            <div>
              <h2 className="admin-card-title">Task Status Monitor</h2>
              <p className="admin-card-subtitle">Query persistent task results from Postgres backend</p>
            </div>
          </div>

          <div className="admin-card-body">
            <div style={{ display: 'flex', gap: 8 }}>
              <div style={{ flex: 1 }}>
                <input
                  type="text"
                  className="input"
                  placeholder="Enter Celery task ID..."
                  value={taskId}
                  onChange={(e) => setTaskId(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleTaskLookup()}
                />
              </div>
              <button className="btn btn-primary" onClick={handleTaskLookup} disabled={taskLoading || !taskId.trim()}>
                {taskLoading ? <Loader2 size={14} className="spin" /> : <Search size={14} />}
                Lookup
              </button>
            </div>

            {taskStatus && (
              <div className="task-result" style={{ marginTop: 16 }}>
                <div className="task-result-header">
                  <span className="badge" style={{
                    background: `color-mix(in srgb, ${getTaskStatusColor(taskStatus.status)} 15%, transparent)`,
                    color: getTaskStatusColor(taskStatus.status),
                  }}>
                    {taskStatus.status}
                  </span>
                  {taskStatus.task_name && (
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                      {taskStatus.task_name}
                    </span>
                  )}
                </div>

                <div style={{ fontSize: '0.78rem', fontFamily: 'monospace', color: 'var(--text-muted)', marginTop: 8, wordBreak: 'break-all' }}>
                  ID: {taskStatus.task_id}
                </div>

                {taskStatus.completed_at && (
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: 4 }}>
                    Completed: {new Date(taskStatus.completed_at).toLocaleString()}
                  </div>
                )}

                {taskStatus.successful && taskStatus.result && (
                  <div className="evidence-panel" style={{ marginTop: 12 }}>
                    <div className="evidence-label">Result</div>
                    <pre style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', margin: 0 }}>
                      {typeof taskStatus.result === 'object' ? JSON.stringify(taskStatus.result, null, 2) : String(taskStatus.result)}
                    </pre>
                  </div>
                )}

                {taskStatus.error && (
                  <div className="evidence-panel" style={{ marginTop: 12, borderColor: 'rgba(var(--severity-critical-raw), 0.2)' }}>
                    <div className="evidence-label" style={{ color: 'var(--severity-critical)' }}>Error</div>
                    <p style={{ fontSize: '0.8rem', color: 'var(--severity-critical)' }}>{taskStatus.error}</p>
                    {taskStatus.traceback && (
                      <pre style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 8, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>
                        {taskStatus.traceback}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Weight Slider Component ── */
function WeightSlider({ label, description, value, onChange }: {
  label: string;
  description: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="weight-slider">
      <div className="weight-slider-header">
        <span className="weight-slider-label">{label}</span>
        <span className="weight-slider-value">{value.toFixed(2)}</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        step={1}
        value={Math.round(value * 100)}
        onChange={(e) => onChange(Number(e.target.value) / 100)}
        className="weight-range"
      />
      <p className="weight-slider-desc">{description}</p>
    </div>
  );
}
