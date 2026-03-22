'use client';

import { useState } from 'react';
import { api } from '@/lib/api';
import { Search, FileText, Sparkles } from 'lucide-react';

interface SearchResult {
  chunk_id: string;
  document_id: string;
  document_title: string;
  content: string;
  score: number;
  page: number | null;
}

export default function SearchPage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);

  const escapeHtml = (value: string) =>
    value
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');

  const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setSearched(true);
    try {
      const data = await api.search(query.trim());
      setResults(data.results);
    } catch (err: any) {
      alert(`Search failed: ${err.message}`);
    } finally {
      setSearching(false);
    }
  };

  const highlightQuery = (text: string) => {
    if (!query.trim()) return escapeHtml(text);
    const words = query.trim().split(/\s+/);
    let highlighted = escapeHtml(text);
    for (const word of words) {
      const safeWord = escapeRegExp(escapeHtml(word));
      if (!safeWord) continue;
      const regex = new RegExp(`(${safeWord})`, 'gi');
      highlighted = highlighted.replace(
        regex,
        '<mark style="background:rgba(var(--accent-indigo-raw),0.25);color:var(--text-primary);border-radius:3px;padding:1px 3px">$1</mark>'
      );
    }
    return highlighted;
  };

  const getScoreColor = (score: number) => {
    if (score > 0.7) return 'var(--accent-emerald)';
    if (score > 0.4) return 'var(--accent-blue)';
    return 'var(--text-muted)';
  };

  return (
    <div className="fade-in">
      <div className="page-header">
        <h1 className="page-title">
          <Sparkles size={24} style={{ color: 'var(--accent-blue)' }} />
          Semantic Search
        </h1>
        <p className="page-subtitle">Search across all documents using natural language</p>
      </div>

      <form onSubmit={handleSearch}>
        <div className="search-bar">
          <Search />
          <input
            type="text"
            className="input"
            placeholder="Search documents... (e.g., 'expense report deadline')"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </form>

      {searching ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 120, borderRadius: 16 }} />)}
        </div>
      ) : searched && results.length === 0 ? (
        <div className="empty-state">
          <Search />
          <p>No results found for &quot;{query}&quot;</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {results.map((result, idx) => (
            <div
              key={result.chunk_id}
              className="card"
              style={{ animation: `fadeInUp 400ms ease-out ${idx * 60}ms both` }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <FileText size={16} style={{ color: 'var(--accent-blue)', opacity: 0.7 }} />
                  <div>
                    <p style={{ fontWeight: 600, fontSize: '0.92rem' }}>{result.document_title || 'Untitled'}</p>
                    {result.page && <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Page {result.page}</p>}
                  </div>
                </div>
                <div className="relevance-gauge" style={{ color: getScoreColor(result.score) }}>
                  <div className="relevance-gauge-bar">
                    <div
                      className="relevance-gauge-fill"
                      style={{ width: `${result.score * 100}%` }}
                    />
                  </div>
                  {(result.score * 100).toFixed(0)}%
                </div>
              </div>
              <p
                style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.7 }}
                dangerouslySetInnerHTML={{
                  __html: highlightQuery(result.content.slice(0, 500) + (result.content.length > 500 ? '...' : '')),
                }}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
