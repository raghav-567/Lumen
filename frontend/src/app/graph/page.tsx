'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '@/lib/api';
import { Network, ZoomIn, ZoomOut, Maximize2, MousePointer, Info } from 'lucide-react';

interface GraphNode {
  id: string;
  name: string;
  type: string;          // always "DOCUMENT" now
  label: string;
  drift_score?: number;
  factual_drift?: number;
  semantic_drift?: number;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  connections?: number;
}

interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  relation: string;
  confidence: number;
  weight?: number;             // # of contradicting claim pairs between the two docs
  avg_confidence?: number;
  types?: Record<string, number>;
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

// Severity scale (DESIGN.md): desaturated cool → warm, drift 0–80+.
// none #4A8C6F · low #B8A53D · medium #C8782E · high #C0392B.
const SEV_STOPS: [number, [number, number, number]][] = [
  [0, [74, 140, 111]],
  [30, [184, 165, 61]],
  [55, [200, 120, 46]],
  [80, [192, 57, 43]],
];
const EDGE = '192, 57, 43'; // --sev-high, the contradiction colour

function driftRGB(drift: number | undefined): [number, number, number] {
  const d = Math.max(0, Math.min(80, drift ?? 0));
  let lo = SEV_STOPS[0], hi = SEV_STOPS[SEV_STOPS.length - 1];
  for (let i = 0; i < SEV_STOPS.length - 1; i++) {
    if (d >= SEV_STOPS[i][0] && d <= SEV_STOPS[i + 1][0]) { lo = SEV_STOPS[i]; hi = SEV_STOPS[i + 1]; break; }
  }
  const span = (hi[0] - lo[0]) || 1;
  const t = (d - lo[0]) / span;
  return lo[1].map((v, j) => Math.round(v + (hi[1][j] - v) * t)) as [number, number, number];
}
function driftColor(drift: number | undefined): string {
  const [r, g, b] = driftRGB(drift);
  return `rgb(${r}, ${g}, ${b})`;
}

// Node radius scales with drift so the most-drifted docs draw the eye.
function driftRadius(drift: number | undefined): number {
  return 9 + Math.min(drift ?? 0, 100) * 0.18; // ~9 (cool) → ~27 (hot)
}

// Edge thickness scales with the number of contradicting claim pairs.
function edgeWidth(weight: number | undefined): number {
  return Math.min(1.5 + (weight ?? 1) * 0.7, 10);
}

export default function GraphPage() {
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [hoveredLink, setHoveredLink] = useState<GraphLink | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const linksRef = useRef<GraphLink[]>([]);
  const hoveredLinkRef = useRef<GraphLink | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animFrameRef = useRef<number>(0);
  const zoomRef = useRef(1);
  const panRef = useRef({ x: 0, y: 0 });
  const isDraggingRef = useRef(false);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const dragNodeRef = useRef<GraphNode | null>(null);
  const nodesRef = useRef<GraphNode[]>([]);
  const nodeMapRef = useRef(new Map<string, GraphNode>());

  useEffect(() => {
    const load = async () => {
      try {
        const data = await api.getGraphVisualization();
        // Count connections per node
        const connCount: Record<string, number> = {};
        data.links.forEach((l: GraphLink) => {
          const sId = typeof l.source === 'string' ? l.source : l.source.id;
          const tId = typeof l.target === 'string' ? l.target : l.target.id;
          connCount[sId] = (connCount[sId] || 0) + 1;
          connCount[tId] = (connCount[tId] || 0) + 1;
        });
        data.nodes.forEach((n: GraphNode) => { n.connections = connCount[n.id] || 0; });
        setGraphData(data);
      } catch (err) {
        console.error('Graph load error:', err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  // Convert screen coords to graph coords
  const screenToGraph = useCallback((sx: number, sy: number) => {
    const zoom = zoomRef.current;
    const pan = panRef.current;
    return {
      x: (sx * 2 - pan.x) / zoom,
      y: (sy * 2 - pan.y) / zoom,
    };
  }, []);

  // Find node at graph coordinates
  const findNodeAt = useCallback((gx: number, gy: number): GraphNode | null => {
    const nodes = nodesRef.current;
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      const dx = gx - n.x!;
      const dy = gy - n.y!;
      const r = driftRadius(n.drift_score);
      if (dx * dx + dy * dy <= (r + 6) * (r + 6)) return n;
    }
    return null;
  }, []);

  // Find a contradiction edge near graph coordinates (point-to-segment distance)
  const findLinkAt = useCallback((gx: number, gy: number): GraphLink | null => {
    const nodeMap = nodeMapRef.current;
    for (const link of linksRef.current) {
      const s = nodeMap.get(typeof link.source === 'string' ? link.source : link.source.id);
      const t = nodeMap.get(typeof link.target === 'string' ? link.target : link.target.id);
      if (!s || !t) continue;
      const dx = t.x! - s.x!, dy = t.y! - s.y!;
      const len2 = dx * dx + dy * dy || 1;
      let u = ((gx - s.x!) * dx + (gy - s.y!) * dy) / len2;
      u = Math.max(0, Math.min(1, u));
      const px = s.x! + u * dx, py = s.y! + u * dy;
      const dist = Math.hypot(gx - px, gy - py);
      if (dist <= edgeWidth(link.weight) / 2 + 6) return link;
    }
    return null;
  }, []);

  // Mouse handlers
  const handleMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const { x: gx, y: gy } = screenToGraph(sx, sy);
    const node = findNodeAt(gx, gy);

    if (node) {
      dragNodeRef.current = node;
    } else {
      isDraggingRef.current = true;
      dragStartRef.current = { x: e.clientX - panRef.current.x, y: e.clientY - panRef.current.y };
    }
  }, [screenToGraph, findNodeAt]);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    setMousePos({ x: sx, y: sy });

    if (dragNodeRef.current) {
      const { x: gx, y: gy } = screenToGraph(sx, sy);
      dragNodeRef.current.x = gx;
      dragNodeRef.current.y = gy;
      dragNodeRef.current.vx = 0;
      dragNodeRef.current.vy = 0;
      return;
    }

    if (isDraggingRef.current) {
      panRef.current = {
        x: e.clientX - dragStartRef.current.x,
        y: e.clientY - dragStartRef.current.y,
      };
      return;
    }

    const { x: gx, y: gy } = screenToGraph(sx, sy);
    const node = findNodeAt(gx, gy);
    setHoveredNode(node);
    const link = node ? null : findLinkAt(gx, gy);
    hoveredLinkRef.current = link;
    setHoveredLink(link);
    if (canvasRef.current) {
      canvasRef.current.style.cursor = node || link ? 'pointer' : 'grab';
    }
  }, [screenToGraph, findNodeAt, findLinkAt]);

  const handleMouseUp = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (dragNodeRef.current) {
      const rect = canvasRef.current!.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const { x: gx, y: gy } = screenToGraph(sx, sy);
      const node = findNodeAt(gx, gy);
      if (node && node.id === dragNodeRef.current.id) {
        setSelectedNode(prev => prev?.id === node.id ? null : node);
      }
    }
    dragNodeRef.current = null;
    isDraggingRef.current = false;
  }, [screenToGraph, findNodeAt]);

  const handleWheel = useCallback((e: React.WheelEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    const rect = canvasRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const oldZoom = zoomRef.current;
    const factor = e.deltaY < 0 ? 1.08 : 0.92;
    const newZoom = Math.max(0.2, Math.min(5, oldZoom * factor));

    // Zoom toward mouse position
    panRef.current = {
      x: panRef.current.x - mx * 2 * (newZoom / oldZoom - 1),
      y: panRef.current.y - my * 2 * (newZoom / oldZoom - 1),
    };
    zoomRef.current = newZoom;
  }, []);

  // Main rendering
  useEffect(() => {
    if (loading || !canvasRef.current || graphData.nodes.length === 0) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d')!;
    const dpr = window.devicePixelRatio || 2;
    const width = canvas.clientWidth * dpr;
    const height = canvas.clientHeight * dpr;
    canvas.width = width;
    canvas.height = height;

    const nodes = [...graphData.nodes];
    const nodeMap = new Map<string, GraphNode>();

    // Initialize positions in a circle
    const cx = width / 2, cy = height / 2;
    nodes.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / nodes.length;
      const spread = Math.min(width, height) * 0.3;
      n.x = cx + Math.cos(angle) * spread + (Math.random() - 0.5) * 60;
      n.y = cy + Math.sin(angle) * spread + (Math.random() - 0.5) * 60;
      n.vx = 0;
      n.vy = 0;
      nodeMap.set(n.id, n);
    });

    nodesRef.current = nodes;
    nodeMapRef.current = nodeMap;
    linksRef.current = graphData.links;

    // Center the view
    panRef.current = { x: 0, y: 0 };
    zoomRef.current = 1;

    const simulate = () => {
      // Repulsion
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[j].x! - nodes[i].x!;
          const dy = nodes[j].y! - nodes[i].y!;
          const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
          const force = 1200 / (dist * dist);
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          nodes[i].vx! -= fx;
          nodes[i].vy! -= fy;
          nodes[j].vx! += fx;
          nodes[j].vy! += fy;
        }
      }

      // Attraction along links
      for (const link of graphData.links) {
        const source = nodeMap.get(typeof link.source === 'string' ? link.source : link.source.id);
        const target = nodeMap.get(typeof link.target === 'string' ? link.target : link.target.id);
        if (!source || !target) continue;
        const dx = target.x! - source.x!;
        const dy = target.y! - source.y!;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const idealDist = link.relation === 'CONTRADICTS' ? 200 : 120;
        const force = (dist - idealDist) * 0.004;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        source.vx! += fx;
        source.vy! += fy;
        target.vx! -= fx;
        target.vy! -= fy;
      }

      // Center gravity + damping
      for (const node of nodes) {
        if (dragNodeRef.current && node.id === dragNodeRef.current.id) continue;
        node.vx! += (cx - node.x!) * 0.0008;
        node.vy! += (cy - node.y!) * 0.0008;
        node.vx! *= 0.88;
        node.vy! *= 0.88;
        node.x! += node.vx!;
        node.y! += node.vy!;
        node.x! = Math.max(40, Math.min(width - 40, node.x!));
        node.y! = Math.max(40, Math.min(height - 40, node.y!));
      }
    };

    const draw = () => {
      const zoom = zoomRef.current;
      const pan = panRef.current;
      const selId = selectedNode?.id;

      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.translate(pan.x, pan.y);
      ctx.scale(zoom, zoom);

      const time = Date.now();

      // Draw links — every edge is an inter-document CONTRADICTS relationship.
      for (const link of graphData.links) {
        const source = nodeMap.get(typeof link.source === 'string' ? link.source : link.source.id);
        const target = nodeMap.get(typeof link.target === 'string' ? link.target : link.target.id);
        if (!source || !target) continue;

        const touchesSel = selId && (
          (typeof link.source === 'string' ? link.source : link.source.id) === selId ||
          (typeof link.target === 'string' ? link.target : link.target.id) === selId
        );
        const isHovered = link === hoveredLinkRef.current;
        const dimmed = (selId && !touchesSel) ? true : false;
        const w = edgeWidth(link.weight);

        // Link line — thickness scales with the # of contradicting claims (weight)
        ctx.beginPath();
        ctx.moveTo(source.x!, source.y!);
        ctx.lineTo(target.x!, target.y!);
        ctx.strokeStyle = dimmed
          ? `rgba(${EDGE}, 0.10)`
          : (isHovered || touchesSel ? `rgba(${EDGE}, 0.95)` : `rgba(${EDGE}, 0.5)`);
        ctx.lineWidth = dimmed ? Math.min(w, 1.5) : w;
        ctx.setLineDash([6, 4]);
        ctx.stroke();
        ctx.setLineDash([]);

        // Animated particle
        if (!dimmed) {
          const t = (time % 2500) / 2500;
          const px = source.x! + (target.x! - source.x!) * t;
          const py = source.y! + (target.y! - source.y!) * t;
          ctx.beginPath();
          ctx.arc(px, py, 2.5, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${EDGE}, 0.95)`;
          ctx.fill();
        }

        // Edge label — number of contradicting claims (light chip, severity text)
        if (!dimmed && zoom > 0.6) {
          const mx = (source.x! + target.x!) / 2;
          const my = (source.y! + target.y!) / 2;
          const label = `${link.weight ?? 1} claim${(link.weight ?? 1) === 1 ? '' : 's'}`;
          ctx.font = '600 9px "Schibsted Grotesk", system-ui';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          const tw = ctx.measureText(label).width + 10;
          ctx.fillStyle = 'rgba(255, 255, 255, 0.92)';
          ctx.fillRect(mx - tw / 2, my - 8, tw, 16);
          ctx.fillStyle = `rgba(${EDGE}, 1)`;
          ctx.fillText(label, mx, my);
        }
      }

      // Draw nodes — documents, colored & sized by drift score.
      for (const node of nodes) {
        const [nr, ng, nb] = driftRGB(node.drift_score);
        const color = `rgb(${nr}, ${ng}, ${nb})`;
        const baseR = driftRadius(node.drift_score);
        const isSelected = selId === node.id;
        const isConnected = selId && graphData.links.some(l => {
          const sId = typeof l.source === 'string' ? l.source : l.source.id;
          const tId = typeof l.target === 'string' ? l.target : l.target.id;
          return sId === node.id || tId === node.id;
        } );
        const dimmed = selId && !isSelected && !isConnected;

        if (dimmed) {
          ctx.globalAlpha = 0.15;
        }

        // Pulsing halo for high-drift documents (drift ≥ 60).
        const isHot = (node.drift_score ?? 0) >= 60;
        if (isHot && !dimmed) {
          const pulse = 0.18 + 0.10 * Math.sin(time / 400);
          ctx.beginPath();
          ctx.arc(node.x!, node.y!, baseR + 10, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${nr}, ${ng}, ${nb}, ${pulse})`;
          ctx.fill();
        }

        // Soft halo
        if (!dimmed) {
          ctx.beginPath();
          ctx.arc(node.x!, node.y!, baseR + 5, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${nr}, ${ng}, ${nb}, 0.12)`;
          ctx.fill();
        }

        // Node circle
        ctx.beginPath();
        ctx.arc(node.x!, node.y!, baseR, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();

        if (isSelected) {
          ctx.strokeStyle = '#1A1A18';
          ctx.lineWidth = 2.5;
          ctx.stroke();
        } else {
          ctx.strokeStyle = `rgba(${nr}, ${ng}, ${nb}, 0.45)`;
          ctx.lineWidth = 1;
          ctx.stroke();
        }

        // Label — near-black on the light canvas
        if (zoom > 0.5) {
          ctx.font = `${isSelected ? '600 ' : ''}${Math.round(11 / Math.max(zoom, 0.6))}px "Schibsted Grotesk", system-ui`;
          ctx.fillStyle = dimmed ? 'rgba(26,26,24,0.25)' : 'rgba(26,26,24,0.85)';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          const label = node.label.length > 18 ? node.label.slice(0, 16) + '…' : node.label;
          ctx.fillText(label, node.x!, node.y! + baseR + 7);
        }

        ctx.globalAlpha = 1;
      }

      ctx.restore();
    };

    const loop = () => {
      simulate();
      draw();
      animFrameRef.current = requestAnimationFrame(loop);
    };

    loop();
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [loading, graphData, selectedNode]);

  const getConnectedLinks = () => {
    if (!selectedNode) return [];
    return graphData.links.filter(l => {
      const sId = typeof l.source === 'string' ? l.source : l.source.id;
      const tId = typeof l.target === 'string' ? l.target : l.target.id;
      return sId === selectedNode.id || tId === selectedNode.id;
    });
  };

  return (
    <div style={{ height: '100vh', position: 'relative', background: 'var(--bg-primary)', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        position: 'absolute', top: 16, left: 16, zIndex: 10,
        display: 'flex', alignItems: 'center', gap: 12, padding: '10px 18px',
        background: 'rgba(255, 255, 255, 0.88)', backdropFilter: 'blur(12px)', boxShadow: 'var(--shadow-md)',
        borderRadius: 14, border: '1px solid var(--border-subtle)',
      }}>
        <Network size={18} style={{ color: 'var(--text-secondary)' }} />
        <span style={{ fontWeight: 600, fontSize: '0.95rem', letterSpacing: '-0.01em' }}>Contradiction Graph</span>
        <span className="badge">{graphData.nodes.length} DOCS</span>
        <span className="badge">{graphData.links.length} EDGES</span>
        {graphData.links.length > 0 && (
          <span className="badge" style={{ background: 'rgba(192, 57, 43, 0.10)', color: 'var(--sev-high)' }}>
            {graphData.links.reduce((s, l) => s + (l.weight ?? 1), 0)} CONTRADICTIONS
          </span>
        )}
      </div>

      {/* Controls */}
      <div style={{
        position: 'absolute', top: 16, right: 16, zIndex: 10,
        display: 'flex', gap: 4,
      }}>
        <button className="btn btn-sm btn-secondary"
          title="Zoom In"
          onClick={() => { zoomRef.current = Math.min(4, zoomRef.current * 1.25); }}>
          <ZoomIn size={14} />
        </button>
        <button className="btn btn-sm btn-secondary"
          title="Zoom Out"
          onClick={() => { zoomRef.current = Math.max(0.2, zoomRef.current * 0.75); }}>
          <ZoomOut size={14} />
        </button>
        <button className="btn btn-sm btn-secondary"
          title="Reset View"
          onClick={() => { zoomRef.current = 1; panRef.current = { x: 0, y: 0 }; setSelectedNode(null); }}>
          <Maximize2 size={14} />
        </button>
      </div>

      {/* Node hover tooltip — drift breakdown */}
      {hoveredNode && !isDraggingRef.current && (
        <div style={{
          position: 'absolute',
          left: mousePos.x + 16, top: mousePos.y - 10,
          zIndex: 20, pointerEvents: 'none',
          padding: '8px 14px',
          background: 'rgba(255, 255, 255, 0.92)', backdropFilter: 'blur(8px)', boxShadow: 'var(--shadow-md)',
          borderRadius: 10, border: '1px solid var(--border-default)',
          maxWidth: 280,
        }}>
          <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 2 }}>{hoveredNode.name}</div>
          <div style={{ fontSize: '0.72rem', color: driftColor(hoveredNode.drift_score), fontWeight: 600 }}>
            Drift {(hoveredNode.drift_score ?? 0).toFixed(1)}
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>
            factual {(hoveredNode.factual_drift ?? 0).toFixed(1)} · semantic {(hoveredNode.semantic_drift ?? 0).toFixed(1)} · {hoveredNode.connections || 0} contradicting docs
          </div>
        </div>
      )}

      {/* Edge hover tooltip — contradiction detail */}
      {hoveredLink && !hoveredNode && !isDraggingRef.current && (
        <div style={{
          position: 'absolute',
          left: mousePos.x + 16, top: mousePos.y - 10,
          zIndex: 20, pointerEvents: 'none',
          padding: '8px 14px',
          background: 'rgba(255, 255, 255, 0.92)', backdropFilter: 'blur(8px)', boxShadow: 'var(--shadow-md)',
          borderRadius: 10, border: '1px solid rgba(192,57,43,0.35)',
          maxWidth: 300,
        }}>
          <div style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--sev-high)', marginBottom: 2 }}>
            {hoveredLink.weight ?? 1} contradicting claim{(hoveredLink.weight ?? 1) === 1 ? '' : 's'}
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
            max confidence {((hoveredLink.confidence ?? 0) * 100).toFixed(0)}% · avg {((hoveredLink.avg_confidence ?? 0) * 100).toFixed(0)}%
          </div>
          {hoveredLink.types && Object.keys(hoveredLink.types).length > 0 && (
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 4 }}>
              {Object.entries(hoveredLink.types).map(([t, c]) => `${t.replace(/_/g, ' ')} ×${c}`).join(', ')}
            </div>
          )}
        </div>
      )}

      {/* Selected node detail panel */}
      {selectedNode && (
        <div style={{
          position: 'absolute', bottom: 16, right: 16, zIndex: 10,
          width: 320, padding: '16px 20px',
          background: 'rgba(255, 255, 255, 0.92)', backdropFilter: 'blur(12px)', boxShadow: 'var(--shadow-md)',
          borderRadius: 14, border: '1px solid var(--border-default)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <div style={{
              width: 12, height: 12, borderRadius: '50%',
              background: driftColor(selectedNode.drift_score),
            }} />
            <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>{selectedNode.name}</span>
          </div>
          {/* Drift breakdown */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            {[
              { label: 'Total', val: selectedNode.drift_score, color: driftColor(selectedNode.drift_score) },
              { label: 'Factual', val: selectedNode.factual_drift, color: 'var(--text-primary)' },
              { label: 'Semantic', val: selectedNode.semantic_drift, color: 'var(--text-primary)' },
            ].map(({ label, val, color }) => (
              <div key={label} style={{
                flex: 1, textAlign: 'center', padding: '6px 4px',
                background: 'var(--bg-secondary)', borderRadius: 8, border: '1px solid var(--border-subtle)',
              }}>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color }}>{(val ?? 0).toFixed(1)}</div>
                <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
            <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--text-muted)', textTransform: 'uppercase', fontSize: '0.68rem', letterSpacing: '0.06em' }}>
              Contradicts ({getConnectedLinks().length})
            </div>
            {getConnectedLinks().slice(0, 8).map((link, i) => {
              const sId = typeof link.source === 'string' ? link.source : link.source.id;
              const tId = typeof link.target === 'string' ? link.target : link.target.id;
              const otherId = sId === selectedNode.id ? tId : sId;
              const otherNode = graphData.nodes.find(n => n.id === otherId);
              return (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '4px 0', borderBottom: '1px solid var(--border-subtle)',
                }}>
                  <span style={{
                    fontSize: '0.68rem', fontWeight: 600, padding: '1px 6px', borderRadius: 4,
                    background: 'rgba(192,57,43,0.10)', color: 'var(--sev-high)',
                  }}>
                    {link.weight ?? 1} claim{(link.weight ?? 1) === 1 ? '' : 's'}
                  </span>
                  <span style={{ color: 'var(--text-primary)', fontSize: '0.78rem' }}>
                    {otherNode?.name || otherId.slice(0, 8)}
                  </span>
                </div>
              );
            })}
          </div>
          <button
            className="btn btn-sm btn-secondary"
            style={{ marginTop: 12, width: '100%', justifyContent: 'center' }}
            onClick={() => setSelectedNode(null)}
          >
            Clear Selection
          </button>
        </div>
      )}

      {/* Legend */}
      {graphData.nodes.length > 0 && (
        <div style={{
          position: 'absolute', bottom: 16, left: 16, zIndex: 10,
          padding: '10px 14px', background: 'rgba(255, 255, 255, 0.88)',
          backdropFilter: 'blur(12px)', borderRadius: 12, boxShadow: 'var(--shadow-md)',
          border: '1px solid var(--border)', fontSize: '0.72rem',
          display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center',
        }}>
          <span style={{ color: 'var(--text-muted)', fontWeight: 600 }}>Drift</span>
          {[
            { label: 'low', d: 10 },
            { label: 'med', d: 45 },
            { label: 'high', d: 80 },
          ].map(({ label, d }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: driftColor(d) }} />
              <span style={{ color: 'var(--text-muted)' }}>{label}</span>
            </div>
          ))}
          {graphData.links.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 14, height: 3, background: 'var(--sev-high)', borderRadius: 2 }} />
              <span style={{ color: 'var(--sev-high)', fontWeight: 600 }}>contradicts (thicker = more)</span>
            </div>
          )}
        </div>
      )}

      {/* Canvas or empty state */}
      {loading ? (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', flexDirection: 'column', gap: 12 }}>
          <div className="spinner" />
          <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Loading contradiction graph…</span>
        </div>
      ) : graphData.nodes.length === 0 ? (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          height: '100%', flexDirection: 'column', gap: 16,
        }}>
          <div style={{
            width: 80, height: 80, borderRadius: 20,
            background: 'var(--bg-subtle)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Network size={36} style={{ color: 'var(--accent-indigo)', opacity: 0.5 }} />
          </div>
          <div style={{ textAlign: 'center' }}>
            <p style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>
              No documents yet
            </p>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', maxWidth: 360, lineHeight: 1.6 }}>
              Upload documents to see the contradiction graph. Documents that contradict each other will be connected by red edges — thicker edges mean more contradicting claims.
            </p>
          </div>
          <div style={{
            display: 'flex', gap: 8, marginTop: 8,
            fontSize: '0.72rem', color: 'var(--text-muted)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px', background: 'var(--bg-secondary)', borderRadius: 6, border: '1px solid var(--border-subtle)' }}>
              <MousePointer size={12} /> Drag to pan
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px', background: 'var(--bg-secondary)', borderRadius: 6, border: '1px solid var(--border-subtle)' }}>
              <ZoomIn size={12} /> Scroll to zoom
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px', background: 'var(--bg-secondary)', borderRadius: 6, border: '1px solid var(--border-subtle)' }}>
              <Info size={12} /> Click nodes for details
            </div>
          </div>
        </div>
      ) : (
        <canvas
          ref={canvasRef}
          style={{ width: '100%', height: '100%', display: 'block' }}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={() => { isDraggingRef.current = false; dragNodeRef.current = null; setHoveredNode(null); }}
          onWheel={handleWheel}
        />
      )}
    </div>
  );
}
