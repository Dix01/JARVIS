/**
 * Neural Memory Galaxy — interactive 3D point cloud of every memory entry.
 *
 * Canvas 2D w/ simulated 3D projection (perspective + depth sort). Categories
 * colored distinctly. Mouse-drag to orbit; auto-rotation when idle. Hover a
 * node for tooltip; clusters labelled at their anchor projection.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { GalaxyCluster, GalaxyNode, MediaCard } from "../../lib/store";

interface PreparedNode extends GalaxyNode {
  // Local position relative to cluster anchor (small jitter).
  px: number; py: number; pz: number;
  // Twinkle phase
  phase: number;
  size: number;
}

const VIEW_SIZE = 1.6;  // world cube extent
const PERSPECTIVE = 3.2;

export default function NeuralGalaxy({ card, large = false }: { card: MediaCard; large?: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const rotationRef = useRef({ x: 0.22, y: 0, vx: 0, vy: 0.0025 });
  const dragRef = useRef<{ x: number; y: number; on: boolean }>({ x: 0, y: 0, on: false });
  const hoverRef = useRef<{ node: PreparedNode | null; sx: number; sy: number } | null>(null);
  const [hoverNode, setHoverNode] = useState<PreparedNode | null>(null);
  const [, force] = useState(0);

  const galaxy = card.galaxy;

  // Prepare node positions once. Each node sits near its cluster anchor with
  // small deterministic jitter.
  const prepared = useMemo<PreparedNode[]>(() => {
    if (!galaxy) return [];
    const seen: Record<string, number> = {};
    return galaxy.nodes.map((n) => {
      const idx = (seen[n.category] = (seen[n.category] ?? -1) + 1);
      // Deterministic jitter from node id
      const seed = hashStr(n.id + idx);
      const r = 0.18 + ((seed & 0xff) / 255) * 0.32; // 0.18..0.5
      const t = ((seed >>> 8) & 0xffff) / 0xffff * Math.PI * 2;
      const p = ((seed >>> 16) & 0xff) / 255 * Math.PI;
      const jx = Math.sin(p) * Math.cos(t) * r;
      const jy = Math.cos(p) * r;
      const jz = Math.sin(p) * Math.sin(t) * r;
      return {
        ...n,
        px: n.anchor[0] + jx,
        py: n.anchor[1] + jy,
        pz: n.anchor[2] + jz,
        phase: (seed & 0xffff) / 0xffff * Math.PI * 2,
        size: 1.4 + ((seed >>> 4) & 0x07) / 7 * 1.8,
      };
    });
  }, [galaxy]);

  // Inter-cluster edges (mostly within-cluster) — keep light
  const edges = useMemo(() => {
    if (!galaxy) return [];
    const out: [number, number][] = [];
    // group by category
    const groups: Record<string, number[]> = {};
    prepared.forEach((n, i) => {
      (groups[n.category] ||= []).push(i);
    });
    for (const list of Object.values(groups)) {
      // chain a few nearest neighbours within cluster
      for (let i = 0; i < list.length - 1; i++) {
        out.push([list[i], list[i + 1]]);
      }
    }
    return out;
  }, [prepared, galaxy]);

  // Render loop
  useEffect(() => {
    const c = canvasRef.current; if (!c) return;
    const ctx = c.getContext("2d"); if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    let raf = 0;

    const resize = () => {
      const w = wrapRef.current?.clientWidth || 600;
      const h = wrapRef.current?.clientHeight || 400;
      c.width = w * dpr; c.height = h * dpr;
      c.style.width = `${w}px`; c.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    if (wrapRef.current) ro.observe(wrapRef.current);

    let t = 0;
    const project = (x: number, y: number, z: number) => {
      const r = rotationRef.current;
      // rotate Y
      const cosY = Math.cos(r.y), sinY = Math.sin(r.y);
      let rx = x * cosY + z * sinY;
      let rz = -x * sinY + z * cosY;
      // rotate X
      const cosX = Math.cos(r.x), sinX = Math.sin(r.x);
      let ry = y * cosX - rz * sinX;
      rz = y * sinX + rz * cosX;
      // perspective
      const w = c.clientWidth, h = c.clientHeight;
      const scale = Math.min(w, h) * 0.42;
      const f = PERSPECTIVE / (PERSPECTIVE - rz);
      const sx = w / 2 + rx * scale * f;
      const sy = h / 2 + ry * scale * f;
      return { sx, sy, depth: rz, f };
    };

    const tick = () => {
      t += 1;
      const r = rotationRef.current;
      if (!dragRef.current.on) {
        r.y += r.vy;
        r.x += r.vx;
        // settle drift to gentle Y rotation
        r.vx *= 0.96;
        r.vy = r.vy * 0.97 + 0.0025 * 0.03;
      }

      const w = c.clientWidth, h = c.clientHeight;
      // background
      ctx.fillStyle = "rgba(2,6,15,0.55)";
      ctx.fillRect(0, 0, w, h);
      // soft vignette
      const grad = ctx.createRadialGradient(w/2, h/2, 30, w/2, h/2, Math.max(w, h) * 0.6);
      grad.addColorStop(0, "rgba(34,211,238,0.06)");
      grad.addColorStop(1, "rgba(2,6,15,0)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);

      // project all nodes
      const proj = prepared.map((n) => ({ n, ...project(n.px, n.py, n.pz) }));
      // sort back-to-front
      proj.sort((a, b) => a.depth - b.depth);

      // edges first (within-cluster spider lines)
      ctx.lineWidth = 0.6;
      for (const [a, b] of edges) {
        const pa = proj.find((p) => p.n === prepared[a]); if (!pa) continue;
        const pb = proj.find((p) => p.n === prepared[b]); if (!pb) continue;
        const alpha = Math.max(0, Math.min(0.45, (pa.depth + pb.depth) * 0.3 + 0.4));
        ctx.strokeStyle = withAlpha(pa.n.color, alpha * 0.45);
        ctx.beginPath();
        ctx.moveTo(pa.sx, pa.sy);
        ctx.lineTo(pb.sx, pb.sy);
        ctx.stroke();
      }

      // nodes
      let hover: PreparedNode | null = null;
      let hoverSx = 0, hoverSy = 0;
      const hoverPx = hoverRef.current?.sx ?? null;
      const hoverPy = hoverRef.current?.sy ?? null;
      for (const p of proj) {
        const twinkle = 0.7 + 0.3 * Math.sin(t * 0.04 + p.n.phase);
        const sz = p.n.size * p.f * twinkle;
        // glow
        ctx.beginPath();
        ctx.fillStyle = withAlpha(p.n.color, Math.min(0.55, 0.25 + p.f * 0.12));
        ctx.arc(p.sx, p.sy, sz * 2.2, 0, Math.PI * 2);
        ctx.fill();
        // core
        ctx.beginPath();
        ctx.fillStyle = withAlpha(p.n.color, 0.95);
        ctx.arc(p.sx, p.sy, sz, 0, Math.PI * 2);
        ctx.fill();
        // hit-test against cursor
        if (hoverPx !== null && hoverPy !== null) {
          const dx = hoverPx - p.sx, dy = hoverPy - p.sy;
          if (dx * dx + dy * dy < (sz * 2.4) * (sz * 2.4)) {
            hover = p.n;
            hoverSx = p.sx; hoverSy = p.sy;
          }
        }
      }

      // cluster labels
      if (galaxy) {
        ctx.font = "10px 'JetBrains Mono', monospace";
        for (const cl of galaxy.clusters) {
          const lp = project(cl.anchor[0], cl.anchor[1], cl.anchor[2]);
          if (lp.depth < -0.6) continue;
          const op = Math.min(1, 0.4 + lp.f * 0.2);
          ctx.fillStyle = withAlpha(cl.color, op);
          ctx.strokeStyle = "rgba(2,6,15,0.85)";
          ctx.lineWidth = 3;
          const label = `${cl.name} · ${cl.count}`;
          ctx.strokeText(label, lp.sx + 8, lp.sy - 8);
          ctx.fillText(label, lp.sx + 8, lp.sy - 8);
          // bracket marker
          ctx.strokeStyle = withAlpha(cl.color, op * 0.85);
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(lp.sx + 1, lp.sy + 6); ctx.lineTo(lp.sx + 6, lp.sy + 6);
          ctx.moveTo(lp.sx + 1, lp.sy + 6); ctx.lineTo(lp.sx + 1, lp.sy + 1);
          ctx.stroke();
        }
      }

      // commit hover
      if (hover !== hoverNode) {
        setHoverNode(hover);
      }
      if (hoverRef.current) {
        hoverRef.current.node = hover;
        hoverRef.current.sx = hoverSx || hoverRef.current.sx;
        hoverRef.current.sy = hoverSy || hoverRef.current.sy;
      }

      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prepared, edges, galaxy]);

  // Input handlers
  useEffect(() => {
    const el = canvasRef.current; if (!el) return;
    const onDown = (e: PointerEvent) => {
      dragRef.current = { x: e.clientX, y: e.clientY, on: true };
      el.setPointerCapture(e.pointerId);
    };
    const onMove = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      hoverRef.current = { node: null, sx: e.clientX - rect.left, sy: e.clientY - rect.top };
      if (!dragRef.current.on) return;
      const dx = e.clientX - dragRef.current.x;
      const dy = e.clientY - dragRef.current.y;
      dragRef.current.x = e.clientX; dragRef.current.y = e.clientY;
      const r = rotationRef.current;
      r.y += dx * 0.005;
      r.x += dy * 0.005;
      r.x = Math.max(-Math.PI/2 + 0.2, Math.min(Math.PI/2 - 0.2, r.x));
      r.vx = dy * 0.0008;
      r.vy = dx * 0.0008;
      force((v) => v + 1);
    };
    const onUp = (e: PointerEvent) => {
      dragRef.current.on = false;
      try { el.releasePointerCapture(e.pointerId); } catch {/**/}
    };
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    el.addEventListener("pointerleave", () => { hoverRef.current = null; setHoverNode(null); });
    return () => {
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
    };
  }, []);

  const totalNodes = galaxy?.nodes.length ?? 0;
  const totalClusters = galaxy?.clusters.length ?? 0;

  return (
    <div ref={wrapRef} className={`relative w-full ${large ? "h-[78vh]" : "h-[60vh]"} bg-jarvis-ink/60 border border-jarvis-aqua/40 overflow-hidden`}>
      <canvas ref={canvasRef} className="block w-full h-full cursor-grab active:cursor-grabbing" />

      {/* Corner brackets */}
      <div className="absolute top-1 left-1 w-3 h-3 border-t border-l border-jarvis-aqua/70 pointer-events-none" />
      <div className="absolute top-1 right-1 w-3 h-3 border-t border-r border-jarvis-aqua/70 pointer-events-none" />
      <div className="absolute bottom-1 left-1 w-3 h-3 border-b border-l border-jarvis-aqua/70 pointer-events-none" />
      <div className="absolute bottom-1 right-1 w-3 h-3 border-b border-r border-jarvis-aqua/70 pointer-events-none" />

      {/* Top HUD */}
      <div className="absolute top-2 left-2 right-2 flex items-center justify-between text-mono text-[10px] pointer-events-none">
        <div className="flex items-center gap-2 text-jarvis-aqua">
          <span className="w-1.5 h-1.5 bg-jarvis-aqua rounded-full animate-pulse" />
          <span className="tracking-widest">NEURAL CLOUD · LIVE</span>
        </div>
        <div className="text-jarvis-cyan/80 tracking-widest bg-jarvis-ink/60 px-1.5 py-0.5 border border-jarvis-aqua/40">
          {totalNodes} NODES · {totalClusters} CLUSTERS
        </div>
      </div>

      {/* Legend */}
      <div className="absolute left-2 bottom-2 max-w-[55%] flex flex-wrap gap-1 text-mono text-[9px]">
        {galaxy?.clusters.map((c) => (
          <span
            key={c.name}
            className="px-1.5 py-0.5 border bg-jarvis-ink/60 tracking-widest"
            style={{ color: c.color, borderColor: withAlpha(c.color, 0.55) }}
          >
            {c.name} · {c.count}
          </span>
        ))}
      </div>

      {/* Prompt */}
      <div className="absolute right-2 bottom-2 text-mono text-[10px] text-jarvis-cyan/70 tracking-widest bg-jarvis-ink/60 px-2 py-0.5 border border-jarvis-aqua/40 pointer-events-none">
        ASK ME TO REMEMBER
      </div>

      {/* Hover tooltip */}
      {hoverNode && hoverRef.current && (
        <div
          className="absolute pointer-events-none text-mono text-[10px] bg-jarvis-ink/90 border max-w-[260px] px-2 py-1"
          style={{
            left: Math.min((hoverRef.current.sx ?? 0) + 10, (wrapRef.current?.clientWidth ?? 600) - 280),
            top: Math.max((hoverRef.current.sy ?? 0) - 30, 4),
            borderColor: withAlpha(hoverNode.color, 0.7),
            color: hoverNode.color,
            boxShadow: `0 0 12px ${withAlpha(hoverNode.color, 0.35)}`,
          }}
        >
          <div className="tracking-widest opacity-75 text-[9px]">{hoverNode.category.toUpperCase()}</div>
          <div className="text-jarvis-aqua truncate">{hoverNode.title}</div>
          {hoverNode.body && (
            <div className="text-jarvis-cyan/70 line-clamp-3 mt-0.5">{hoverNode.body}</div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── helpers ── */
function withAlpha(hex: string, a: number): string {
  // hex "#rrggbb" → "rgba(r,g,b,a)"
  const m = hex.match(/^#([0-9a-f]{6})$/i);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 0xff},${(n >> 8) & 0xff},${n & 0xff},${a})`;
}

function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
