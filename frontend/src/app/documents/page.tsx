'use client';

import { useEffect, useState, useRef } from 'react';
import { api } from '@/lib/api';
import {
  FileText, Upload, Trash2, Clock,
  CheckCircle2, Loader2, AlertTriangle,
} from 'lucide-react';

interface Doc {
  id: string;
  title: string;
  filename: string;
  file_type: string;
  file_size: number | null;
  drift_score: number;
  semantic_drift_score: number;
  factual_drift_score: number;
  drift_type: string | null;
  is_processed: boolean;
  created_at: string;
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadMsg, setUploadMsg] = useState<{ type: 'error' | 'info' | 'success'; text: string } | null>(null);

  const loadDocs = async () => {
    try {
      const data = await api.listDocuments();
      setDocs(data.documents);
      setTotal(data.total);
    } catch (err) {
      console.error('Failed to load docs:', err);
    } finally {
      setLoading(false);
    }
  };

  // Drift/contradiction scoring runs asynchronously after upload (parse →
  // embed → pairwise NLI → recalc), so a doc's drift can land seconds-to-minutes
  // after it first appears. Poll so the UI reflects backend scores without a
  // manual reload — otherwise an uploaded doc shows 0 forever. Skip background
  // tabs to avoid needless requests.
  useEffect(() => {
    loadDocs();
    const id = setInterval(() => {
      if (typeof document === 'undefined' || document.visibilityState === 'visible') {
        loadDocs();
      }
    }, 10000);
    return () => clearInterval(id);
  }, []);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadMsg(null);
    try {
      const result = await api.uploadDocument(file);
      await loadDocs();
      if (result.version_number && result.version_number > 1) {
        setUploadMsg({ type: 'success', text: `Uploaded as version ${result.version_number} (supersedes previous version)` });
      }
    } catch (err: any) {
      if (err.status === 409) {
        const data = err.data || {};
        setUploadMsg({
          type: 'info',
          text: `Duplicate detected: "${data.existing_title || 'document'}" already exists with identical content.`,
        });
      } else {
        setUploadMsg({ type: 'error', text: `Upload failed: ${err.message}` });
      }
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
      setTimeout(() => setUploadMsg(null), 8000);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this document?')) return;
    try {
      await api.deleteDocument(id);
      await loadDocs();
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  const formatSize = (bytes: number | null) => {
    if (!bytes) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  };

  const getDriftColor = (score: number) => {
    if (score >= 60) return 'var(--severity-critical)';
    if (score >= 30) return 'var(--severity-high)';
    if (score >= 10) return 'var(--severity-medium)';
    return 'var(--accent-emerald)';
  };

  return (
    <div className="fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title"><FileText size={24} /> Documents</h1>
          <p className="page-subtitle">{total} documents in your knowledge base</p>
        </div>
        <div>
          <input type="file" ref={fileInputRef} onChange={handleUpload} style={{ display: 'none' }}
            accept=".pdf,.docx,.txt,.md" />
          <button className="btn btn-primary" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
            {uploading ? <><Loader2 size={16} className="spin" /> Uploading...</> : <><Upload size={16} /> Upload</>}
          </button>
        </div>
      </div>

      {/* Upload message toast */}
      {uploadMsg && (
        <div className={`upload-toast toast-${uploadMsg.type}`}>
          {uploadMsg.type === 'info' && <AlertTriangle size={14} />}
          {uploadMsg.type === 'success' && <CheckCircle2 size={14} />}
          {uploadMsg.type === 'error' && <AlertTriangle size={14} />}
          {uploadMsg.text}
        </div>
      )}

      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 60, borderRadius: 12 }} />)}
        </div>
      ) : docs.length === 0 ? (
        <div className="empty-state">
          <FileText /><p>No documents yet. Upload your first document to get started.</p>
        </div>
      ) : (
        <div className="table-wrapper">
          <table className="table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Type</th>
                <th>Size</th>
                <th>Inconsistency</th>
                <th>Semantic Drift</th>
                <th>Status</th>
                <th>Uploaded</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((doc, idx) => (
                <tr key={doc.id} style={{ animation: `fadeInUp 300ms ease-out ${idx * 30}ms both` }}>
                  <td style={{ fontWeight: 500, overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
                    {doc.title}
                    {(doc as any).version_number > 1 && (
                      <span className="badge" style={{ marginLeft: 6, fontSize: '0.6rem' }}>
                        v{(doc as any).version_number}
                      </span>
                    )}
                  </td>
                  <td><span className="badge">{doc.file_type}</span></td>
                  <td style={{ whiteSpace: 'nowrap' }}>{formatSize(doc.file_size)}</td>
                  <td>
                    <span style={{ color: getDriftColor(doc.factual_drift_score || 0), fontWeight: 600 }}>
                      {(doc.factual_drift_score || 0).toFixed(1)}
                    </span>
                  </td>
                  <td>
                    <span style={{ color: getDriftColor(doc.semantic_drift_score || 0), fontWeight: 600 }}>
                      {(doc.semantic_drift_score || 0).toFixed(1)}
                    </span>
                  </td>
                  <td>
                    {doc.is_processed ? (
                      <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--accent-emerald)', fontSize: '0.8rem' }}>
                        <CheckCircle2 size={14} /> Processed
                      </span>
                    ) : (
                      <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                        <Clock size={14} /> Pending
                      </span>
                    )}
                  </td>
                  <td style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    {new Date(doc.created_at).toLocaleDateString()}
                  </td>
                  <td>
                    <button className="btn btn-sm btn-secondary" onClick={() => handleDelete(doc.id)}>
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
