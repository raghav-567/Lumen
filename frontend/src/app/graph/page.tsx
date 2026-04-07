'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '@/lib/api';
import { Network, ZoomIn, ZoomOut, Maximize2, MousePointer, Info } from 'lucide-react';

interface GraphNode {
  id: string;
  name: string;
  type: string;
  label: string;
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
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

const TYPE_COLORS: Record<string, string> = {
  PERSON: '#a78bfa',
  ORGANIZATION: '#60a5fa',
  POLICY: '#fbbf24',
  CONCEPT: '#34d399',
  TECHNOLOGY: '#22d3ee',
  REGULATION: '#f87171',
  OTHER: '#9ca3af',
};

export default function GraphPage() {
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
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
      const r = 8 + (n.connections || 0) * 1.5;
      if (dx * dx + dy * dy <= (r + 6) * (r + 6)) return n;
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
    if (canvasRef.current) {
      canvasRef.current.style.cursor = node ? 'pointer' : 'grab';
    }
  }, [screenToGraph, findNodeAt]);

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

      // Draw links
      for (const link of graphData.links) {
        const source = nodeMap.get(typeof link.source === 'string' ? link.source : link.source.id);
        const target = nodeMap.get(typeof link.target === 'string' ? link.target : link.target.id);
        if (!source || !target) continue;

        const isContradiction = link.relation === 'CONTRADICTS';
        const isHighlighted = selId && (
          (typeof link.source === 'string' ? link.source : link.source.id) === selId ||
          (typeof link.target === 'string' ? link.target : link.target.id) === selId
        );

        const dimmed = selId && !isHighlighted;

        // Link line
        ctx.beginPath();
        ctx.moveTo(source.x!, source.y!);
        ctx.lineTo(target.x!, target.y!);

        if (isContradiction) {
          ctx.strokeStyle = dimmed ? 'rgba(239, 68, 68, 0.08)' : 'rgba(239, 68, 68, 0.5)';
          ctx.lineWidth = dimmed ? 1 : 2.5;
          ctx.setLineDash([6, 4]);
        } else {
          ctx.strokeStyle = dimmed ? 'rgba(255,255,255,0.02)' : (isHighlighted ? 'rgba(124, 92, 252, 0.3)' : 'rgba(255,255,255,0.06)');
          ctx.lineWidth = isHighlighted ? 1.5 : 0.8;
          ctx.setLineDash([]);
        }
        ctx.stroke();
        ctx.setLineDash([]);

        // Arrow
        if (!dimmed) {
          const angle = Math.atan2(target.y! - source.y!, target.x! - source.x!);
          const tr = 8 + (target.connections || 0) * 1.5;
          const ax = target.x! - Math.cos(angle) * (tr + 4);
          const ay = target.y! - Math.sin(angle) * (tr + 4);
          const arrowSize = isContradiction ? 6 : 4;
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(ax - arrowSize * Math.cos(angle - 0.4), ay - arrowSize * Math.sin(angle - 0.4));
          ctx.lineTo(ax - arrowSize * Math.cos(angle + 0.4), ay - arrowSize * Math.sin(angle + 0.4));
          ctx.closePath();
          ctx.fillStyle = isContradiction ? 'rgba(239, 68, 68, 0.6)' : 'rgba(255,255,255,0.15)';
          ctx.fill();
        }

        // Animated particle
        if (!dimmed) {
          const t = (time % 2500) / 2500;
          const px = source.x! + (target.x! - source.x!) * t;
          const py = source.y! + (target.y! - source.y!) * t;
          ctx.beginPath();
          ctx.arc(px, py, isContradiction ? 2.5 : 1.5, 0, Math.PI * 2);
          ctx.fillStyle = isContradiction ? 'rgba(239, 68, 68, 0.9)' : 'rgba(124, 92, 252, 0.3)';
          ctx.fill();
        }

        // Relation label
        if (!dimmed && zoom > 0.6) {
          const mx = (source.x! + target.x!) / 2;
          const my = (source.y! + target.y!) / 2;
          const label = link.relation.replace(/_/g, ' ');

          ctx.font = isContradiction ? 'bold 9px system-ui' : '8px system-ui';
          ctx.fillStyle = isContradiction ? 'rgba(239, 68, 68, 0.85)' : 'rgba(255,255,255,0.22)';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';

          // Background for readability
          if (isContradiction || isHighlighted) {
            const tw = ctx.measureText(label).width + 8;
            ctx.fillStyle = 'rgba(10, 10, 15, 0.7)';
            ctx.fillRect(mx - tw / 2, my - 7, tw, 14);
            ctx.fillStyle = isContradiction ? 'rgba(239, 68, 68, 0.9)' : 'rgba(124, 92, 252, 0.7)';
          }

          ctx.fillText(label, mx, my);
        }
      }

      // Draw nodes
      for (const node of nodes) {
        const color = TYPE_COLORS[node.type] || TYPE_COLORS.OTHER;
        const baseR = 8 + (node.connections || 0) * 1.5;
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

        // Pulsing glow for selected or contradiction-involved
        const hasContradiction = graphData.links.some(l =>
          l.relation === 'CONTRADICTS' && (
            (typeof l.source === 'string' ? l.source : l.source.id) === node.id ||
            (typeof l.target === 'string' ? l.target : l.target.id) === node.id
          )
        );

        if (hasContradiction && !dimmed) {
          const pulse = 0.3 + 0.15 * Math.sin(time / 400);
          ctx.beginPath();
          ctx.arc(node.x!, node.y!, baseR + 10, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(239, 68, 68, ${pulse})`;
          ctx.fill();
        }

        // Outer glow
        if (!dimmed) {
          ctx.beginPath();
          ctx.arc(node.x!, node.y!, baseR + 5, 0, Math.PI * 2);
          ctx.fillStyle = `${color}18`;
          ctx.fill();
        }

        // Node circle
        ctx.beginPath();
        ctx.arc(node.x!, node.y!, baseR, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();

        if (isSelected) {
          ctx.strokeStyle = '#fff';
          ctx.lineWidth = 2.5;
          ctx.stroke();
        } else {
          ctx.strokeStyle = `${color}60`;
          ctx.lineWidth = 1;
          ctx.stroke();
        }

        // Label
        if (zoom > 0.5) {
          ctx.font = `${isSelected ? 'bold ' : ''}${Math.round(10 / Math.max(zoom, 0.6))}px system-ui`;
          ctx.fillStyle = dimmed ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.8)';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'top';
          const label = node.label.length > 18 ? node.label.slice(0, 16) + '…' : node.label;
          ctx.fillText(label, node.x!, node.y! + baseR + 6);
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
        background: 'rgba(18, 18, 26, 0.85)', backdropFilter: 'blur(12px)',
        borderRadius: 14, border: '1px solid var(--border-subtle)',
      }}>
        <Network size={18} style={{ color: 'var(--accent-indigo)' }} />
        <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>Knowledge Graph</span>
        <span className="badge" style={{ background: 'rgba(124, 92, 252, 0.12)', color: 'var(--accent-indigo)' }}>
          {graphData.nodes.length} NODES
        </span>
        <span className="badge" style={{ background: 'rgba(96, 165, 250, 0.12)', color: '#60a5fa' }}>
          {graphData.links.length} LINKS
        </span>
        {graphData.links.filter(l => l.relation === 'CONTRADICTS').length > 0 && (
          <span className="badge" style={{ background: 'rgba(239, 68, 68, 0.12)', color: '#ef4444' }}>
            {graphData.links.filter(l => l.relation === 'CONTRADICTS').length} CONTRADICTIONS
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

      {/* Hover tooltip */}
      {hoveredNode && !isDraggingRef.current && (
        <div style={{
          position: 'absolute',
          left: mousePos.x + 16, top: mousePos.y - 10,
          zIndex: 20, pointerEvents: 'none',
          padding: '8px 14px',
          background: 'rgba(18, 18, 26, 0.92)', backdropFilter: 'blur(8px)',
          borderRadius: 10, border: '1px solid var(--border-default)',
          maxWidth: 280,
        }}>
          <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: 2 }}>{hoveredNode.name}</div>
          <div style={{ fontSize: '0.72rem', color: TYPE_COLORS[hoveredNode.type] || '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {hoveredNode.type}
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>
            {hoveredNode.connections || 0} connections · Click to highlight
          </div>
        </div>
      )}

      {/* Selected node detail panel */}
      {selectedNode && (
        <div style={{
          position: 'absolute', bottom: 16, right: 16, zIndex: 10,
          width: 320, padding: '16px 20px',
          background: 'rgba(18, 18, 26, 0.92)', backdropFilter: 'blur(12px)',
          borderRadius: 14, border: '1px solid var(--border-default)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <div style={{
              width: 12, height: 12, borderRadius: '50%',
              background: TYPE_COLORS[selectedNode.type] || '#9ca3af',
            }} />
            <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>{selectedNode.name}</span>
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 12 }}>
            {selectedNode.type} · {selectedNode.connections || 0} connections
          </div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
            <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--text-muted)', textTransform: 'uppercase', fontSize: '0.68rem', letterSpacing: '0.06em' }}>
              Relations
            </div>
            {getConnectedLinks().slice(0, 8).map((link, i) => {
              const sId = typeof link.source === 'string' ? link.source : link.source.id;
              const tId = typeof link.target === 'string' ? link.target : link.target.id;
              const otherId = sId === selectedNode.id ? tId : sId;
              const otherNode = graphData.nodes.find(n => n.id === otherId);
              const isContra = link.relation === 'CONTRADICTS';
              return (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '4px 0', borderBottom: '1px solid var(--border-subtle)',
                }}>
                  <span style={{
                    fontSize: '0.68rem', fontWeight: 600, padding: '1px 6px', borderRadius: 4,
                    background: isContra ? 'rgba(239,68,68,0.12)' : 'rgba(124,92,252,0.1)',
                    color: isContra ? '#ef4444' : 'var(--accent-indigo)',
                  }}>
                    {link.relation.replace(/_/g, ' ')}
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
          padding: '10px 14px', background: 'rgba(18, 18, 26, 0.85)',
          backdropFilter: 'blur(12px)', borderRadius: 12,
          border: '1px solid var(--border-subtle)', fontSize: '0.72rem',
          display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center',
        }}>
          {Object.entries(TYPE_COLORS).filter(([type]) =>
            graphData.nodes.some(n => n.type === type)
          ).map(([type, color]) => (
            <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: color }} />
              <span style={{ color: 'var(--text-muted)' }}>{type}</span>
            </div>
          ))}
          {graphData.links.some(l => l.relation === 'CONTRADICTS') && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 14, height: 2, background: '#ef4444', borderRadius: 2 }} />
              <span style={{ color: '#ef4444', fontWeight: 600 }}>CONTRADICTS</span>
            </div>
          )}
        </div>
      )}

      {/* Canvas or empty state */}
      {loading ? (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', flexDirection: 'column', gap: 12 }}>
          <div className="spinner" />
          <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Loading knowledge graph…</span>
        </div>
      ) : graphData.nodes.length === 0 ? (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          height: '100%', flexDirection: 'column', gap: 16,
        }}>
          <div style={{
            width: 80, height: 80, borderRadius: 20,
            background: 'rgba(124, 92, 252, 0.08)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Network size={36} style={{ color: 'var(--accent-indigo)', opacity: 0.5 }} />
          </div>
          <div style={{ textAlign: 'center' }}>
            <p style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 6 }}>
              No entities found
            </p>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', maxWidth: 360, lineHeight: 1.6 }}>
              Upload and process documents to build the knowledge graph. Entities, relationships, and contradictions will appear here automatically.
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
