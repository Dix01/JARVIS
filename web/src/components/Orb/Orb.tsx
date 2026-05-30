/**
 * JARVIS Orb — v5 "Reference Dial".
 *
 * Flat 2D composition matching canonical fan-art reference:
 *   - tick-mark outer ring
 *   - segmented vertical-bar ring on top arc
 *   - thick mid ring with bracket cutouts on sides
 *   - amber accent dots + amber side brackets
 *   - inner compass dial with fine radial markings
 *   - centered "J.A.R.V.I.S." text
 *
 * Implemented in SVG so it stays crisp at any scale. Each layer rotates at
 * its own speed via CSS animation; state-driven palette + speed multiplier
 * is patched in via JS for cyan/violet/aqua transitions.
 */
import { useEffect, useRef } from "react";
import { useStore, type OrbState } from "../../lib/store";

const PALETTE: Record<OrbState, {
  cyan: string;    // primary stroke
  glow: string;    // soft accent
  amber: string;   // status pip
  speed: number;   // multiplier
  intensity: number;
}> = {
  idle:      { cyan: "#22d3ee", glow: "#67e8f9", amber: "#facc15", speed: 1.0, intensity: 0.85 },
  listening: { cyan: "#5ee9ff", glow: "#a7f3ff", amber: "#fde047", speed: 1.6, intensity: 1.10 },
  thinking:  { cyan: "#9b8cff", glow: "#c4b5fd", amber: "#f59e0b", speed: 2.8, intensity: 1.20 },
  speaking:  { cyan: "#67e8f9", glow: "#a5f3fc", amber: "#fde68a", speed: 1.3, intensity: 1.40 },
};

export default function Orb() {
  const ref = useRef<HTMLDivElement>(null);
  const cur = useRef({ cyan: PALETTE.idle.cyan, glow: PALETTE.idle.glow, amber: PALETTE.idle.amber, speed: 1, intensity: 0.85, audio: 0 });

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const st = useStore.getState();
      const t = PALETTE[st.orbState];
      const c = cur.current;
      const k = 0.08;
      c.intensity += (t.intensity * (1 + st.audioLevel * 0.6) - c.intensity) * k;
      c.speed     += (t.speed - c.speed) * k;
      c.audio     += (st.audioLevel - c.audio) * k * 2;
      // lerp hex colors via DOM CSS vars (we just snap when state changes —
      // the CSS transition smooths it).
      c.cyan  = t.cyan;
      c.glow  = t.glow;
      c.amber = t.amber;
      if (ref.current) {
        ref.current.style.setProperty("--orb-cyan",  c.cyan);
        ref.current.style.setProperty("--orb-glow",  c.glow);
        ref.current.style.setProperty("--orb-amber", c.amber);
        ref.current.style.setProperty("--orb-speed", `${c.speed.toFixed(3)}`);
        ref.current.style.setProperty("--orb-intensity", c.intensity.toFixed(3));
        ref.current.style.setProperty("--orb-audio", c.audio.toFixed(3));
      }
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div
      ref={ref}
      className="absolute inset-0 pointer-events-none flex items-center justify-center"
      style={{
        // Defaults so the CSS animations don't choke before first tick.
        ["--orb-cyan"  as any]: PALETTE.idle.cyan,
        ["--orb-glow"  as any]: PALETTE.idle.glow,
        ["--orb-amber" as any]: PALETTE.idle.amber,
        ["--orb-speed" as any]: 1,
        ["--orb-intensity" as any]: 0.85,
        ["--orb-audio" as any]: 0,
      }}
    >
      <div className="relative w-[clamp(280px,38vmin,560px)] aspect-square">
        {/* Volumetric blue halo — breathes + brightens with voice */}
        <div
          className="absolute inset-0 rounded-full"
          style={{
            background:
              "radial-gradient(circle at center, color-mix(in srgb, var(--orb-glow) 28%, transparent) 0%, transparent 58%)",
            filter: "blur(8px)",
            opacity: "calc(var(--orb-intensity) * 0.9 + var(--orb-audio) * 0.4)",
            transform: "scale(calc(1 + var(--orb-audio) * 0.18))",
            transition: "background 0.6s ease",
          }}
        />

        {/* SVG dial */}
        <svg
          viewBox="-100 -100 200 200"
          className="absolute inset-0 w-full h-full"
          style={{
            filter:
              "drop-shadow(0 0 calc(6px + var(--orb-audio) * 9px) color-mix(in srgb, var(--orb-glow) 70%, transparent)) drop-shadow(0 0 calc(18px + var(--orb-audio) * 20px) color-mix(in srgb, var(--orb-glow) 35%, transparent))",
          }}
        >
          <defs>
            <linearGradient id="ring-fade" x1="0" y1="-1" x2="0" y2="1">
              <stop offset="0%"  stopColor="var(--orb-cyan)" stopOpacity="1" />
              <stop offset="100%" stopColor="var(--orb-cyan)" stopOpacity="0.45" />
            </linearGradient>
            <radialGradient id="core-fill" cx="50%" cy="50%" r="50%">
              <stop offset="0%"  stopColor="var(--orb-cyan)" stopOpacity="0.30" />
              <stop offset="60%" stopColor="var(--orb-cyan)" stopOpacity="0.05" />
              <stop offset="100%" stopColor="var(--orb-cyan)" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="reactor-core" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stopColor="#ffffff"        stopOpacity="0.95" />
              <stop offset="24%"  stopColor="var(--orb-glow)" stopOpacity="0.85" />
              <stop offset="58%"  stopColor="var(--orb-cyan)" stopOpacity="0.45" />
              <stop offset="100%" stopColor="var(--orb-cyan)" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="reactor-bloom" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stopColor="var(--orb-glow)" stopOpacity="0.5" />
              <stop offset="68%"  stopColor="var(--orb-cyan)" stopOpacity="0.12" />
              <stop offset="100%" stopColor="var(--orb-cyan)" stopOpacity="0" />
            </radialGradient>
          </defs>

          {/* Soft inner fill */}
          <circle cx="0" cy="0" r="42" fill="url(#core-fill)" />

          {/* ─── L1 outermost: tick ring (slow CCW) ─── */}
          <g style={{ animation: "orb-spin-ccw calc(38s / var(--orb-speed)) linear infinite", transformOrigin: "0 0" }}>
            <Ticks radius={92} count={120} long={3} short={1.4} thick={0.5} color="var(--orb-cyan)" majorEvery={5} majorLen={5} />
            <circle cx="0" cy="0" r="88" fill="none" stroke="var(--orb-cyan)" strokeOpacity="0.25" strokeWidth="0.4" />
          </g>

          {/* ─── L2 segmented vertical bars (top arc only) — slow CW ─── */}
          <g style={{ animation: "orb-spin calc(50s / var(--orb-speed)) linear infinite", transformOrigin: "0 0" }}>
            <TopArcBars radius={80} count={40} long={6} thick={1.0} color="var(--orb-cyan)" />
          </g>

          {/* ─── L3 thick ring with bracket cutouts ─── */}
          <g style={{ animation: "orb-spin-ccw calc(60s / var(--orb-speed)) linear infinite", transformOrigin: "0 0" }}>
            <BracketRing radius={70} thickness={4.5} gapDeg={26} color="var(--orb-cyan)" />
            {/* Amber pips at 10° → top arc */}
            <AmberDots radius={70} count={6} startDeg={-25} endDeg={25} color="var(--orb-amber)" r={1.6} />
          </g>

          {/* ─── L4 amber side brackets (static, just rotates very slowly) ─── */}
          <g style={{ animation: "orb-spin calc(180s / var(--orb-speed)) linear infinite", transformOrigin: "0 0" }}>
            <AmberBracket angleDeg={-100} radius={60} size={5} color="var(--orb-amber)" />
            <AmberBracket angleDeg={80}   radius={60} size={5} color="var(--orb-amber)" />
          </g>

          {/* ─── L5 inner dashed ring (medium CCW) ─── */}
          <g style={{ animation: "orb-spin-ccw calc(28s / var(--orb-speed)) linear infinite", transformOrigin: "0 0" }}>
            <circle
              cx="0" cy="0" r="54"
              fill="none" stroke="var(--orb-cyan)" strokeWidth="0.6"
              strokeDasharray="2 2.4" strokeOpacity="0.85"
            />
          </g>

          {/* ─── L6 inner compass ticks (fast CW) ─── */}
          <g style={{ animation: "orb-spin calc(16s / var(--orb-speed)) linear infinite", transformOrigin: "0 0" }}>
            <Ticks radius={48} count={72} long={2} short={0.9} thick={0.35} color="var(--orb-cyan)" majorEvery={6} majorLen={3.5} />
          </g>

          {/* ─── L7 innermost solid ring ─── */}
          <circle cx="0" cy="0" r="42" fill="none" stroke="var(--orb-cyan)" strokeWidth="0.7" strokeOpacity="0.9" />
          <circle cx="0" cy="0" r="39" fill="none" stroke="var(--orb-glow)" strokeWidth="0.4" strokeOpacity="0.55" />

          {/* ─── Arc-reactor core — volumetric, breathes with voice ─── */}
          <g style={{ transformOrigin: "0 0", transform: "scale(calc(1 + var(--orb-audio) * 0.5))" }}>
            <circle
              cx="0" cy="0" r="33" fill="url(#reactor-bloom)"
              style={{ opacity: "calc(0.4 + var(--orb-audio) * 0.55)" }}
            />
            <circle
              cx="0" cy="0" r="15" fill="url(#reactor-core)"
              style={{
                opacity: "calc(0.55 + var(--orb-audio) * 0.45)",
                filter: "drop-shadow(0 0 calc(4px + var(--orb-audio) * 16px) var(--orb-glow))",
              }}
            />
            {/* Triangular reactor coil — the Mark arc-reactor motif, slow spin */}
            <g style={{ animation: "orb-spin calc(24s / var(--orb-speed)) linear infinite", transformOrigin: "0 0", opacity: 0.8 }}>
              <ReactorTri r={10.5} color="var(--orb-glow)" />
            </g>
          </g>

          {/* ─── Center text ─── */}
          <text
            x="0" y="2.5"
            textAnchor="middle"
            fontFamily="Orbitron, sans-serif"
            fontSize="9.5"
            letterSpacing="2"
            fill="var(--orb-glow)"
            style={{
              filter: "drop-shadow(0 0 calc(2px + var(--orb-audio) * 6px) var(--orb-glow))",
              opacity: "calc(0.85 * var(--orb-intensity))",
            }}
          >
            J.A.R.V.I.S.
          </text>
          {/* Subtitle */}
          <text
            x="0" y="9"
            textAnchor="middle"
            fontFamily="JetBrains Mono, monospace"
            fontSize="3.4"
            letterSpacing="1.4"
            fill="var(--orb-cyan)"
            opacity="0.55"
          >
            MARK · IV
          </text>
        </svg>

        {/* CSS keyframes injected once */}
        <style>{`
          @keyframes orb-spin     { from { transform: rotate(0deg);  } to { transform: rotate(360deg);  } }
          @keyframes orb-spin-ccw { from { transform: rotate(360deg);} to { transform: rotate(0deg);    } }
        `}</style>
      </div>
    </div>
  );
}

/* ───────────── Sub-components (SVG primitives) ───────────── */

function Ticks({
  radius, count, long, short, thick, color, majorEvery, majorLen,
}: {
  radius: number; count: number; long: number; short: number;
  thick: number; color: string; majorEvery: number; majorLen: number;
}) {
  const out = [];
  for (let i = 0; i < count; i++) {
    const a = (i / count) * 360;
    const major = i % majorEvery === 0;
    const len = major ? majorLen : (i % 2 === 0 ? long : short);
    out.push(
      <line
        key={i}
        x1={radius} y1={0}
        x2={radius - len} y2={0}
        stroke={color}
        strokeOpacity={major ? 0.95 : 0.55}
        strokeWidth={major ? thick * 1.4 : thick}
        transform={`rotate(${a})`}
      />
    );
  }
  return <>{out}</>;
}

function TopArcBars({
  radius, count, long, thick, color,
}: { radius: number; count: number; long: number; thick: number; color: string }) {
  const out = [];
  // Bars span from -55° to +55° around top.
  const start = -55, end = 55;
  for (let i = 0; i < count; i++) {
    const a = start + (end - start) * (i / (count - 1));
    out.push(
      <line
        key={i}
        x1="0" y1={-radius}
        x2="0" y2={-(radius - long)}
        stroke={color}
        strokeOpacity={0.85}
        strokeWidth={thick}
        transform={`rotate(${a})`}
      />
    );
  }
  return <>{out}</>;
}

function BracketRing({
  radius, thickness, gapDeg, color,
}: { radius: number; thickness: number; gapDeg: number; color: string }) {
  // Two big arcs separated by left & right gaps (the bracket cutouts).
  const half = gapDeg / 2;
  const arc = (startDeg: number, endDeg: number) => {
    const rad = (d: number) => (d - 90) * Math.PI / 180; // SVG 0deg = up
    const x1 = Math.cos(rad(startDeg)) * radius;
    const y1 = Math.sin(rad(startDeg)) * radius;
    const x2 = Math.cos(rad(endDeg)) * radius;
    const y2 = Math.sin(rad(endDeg)) * radius;
    const large = (endDeg - startDeg) > 180 ? 1 : 0;
    return `M ${x1} ${y1} A ${radius} ${radius} 0 ${large} 1 ${x2} ${y2}`;
  };
  return (
    <>
      <path d={arc(-90 + half, 90 - half)}  fill="none" stroke={color} strokeWidth={thickness} strokeOpacity="0.85" strokeLinecap="butt" />
      <path d={arc(90 + half,  270 - half)} fill="none" stroke={color} strokeWidth={thickness} strokeOpacity="0.85" strokeLinecap="butt" />
      {/* Bracket cap markers at the cutouts */}
      {[-(90 + half), -(90 - half), (90 + half), (90 - half)].map((deg, i) => (
        <line
          key={i}
          x1="0" y1={-(radius - thickness / 2 - 1)}
          x2="0" y2={-(radius + thickness / 2 + 1)}
          stroke={color} strokeWidth="0.7" strokeOpacity="0.8"
          transform={`rotate(${deg + 90})`}
        />
      ))}
    </>
  );
}

function AmberDots({
  radius, count, startDeg, endDeg, color, r,
}: { radius: number; count: number; startDeg: number; endDeg: number; color: string; r: number }) {
  const out = [];
  for (let i = 0; i < count; i++) {
    const a = startDeg + (endDeg - startDeg) * (i / (count - 1));
    const rad = (a - 90) * Math.PI / 180;
    const x = Math.cos(rad) * radius;
    const y = Math.sin(rad) * radius;
    out.push(
      <circle key={i} cx={x} cy={y} r={r} fill={color}
        style={{ filter: `drop-shadow(0 0 2px ${color})` }}
      />
    );
  }
  return <>{out}</>;
}

function ReactorTri({ r, color }: { r: number; color: string }) {
  // Equilateral triangle (pointing up) with coil nodes at each vertex —
  // the iconic Mark arc-reactor motif.
  const pts = [0, 120, 240].map((deg) => {
    const rad = (deg - 90) * Math.PI / 180;
    return [Math.cos(rad) * r, Math.sin(rad) * r] as const;
  });
  const path = `M ${pts[0][0]} ${pts[0][1]} L ${pts[1][0]} ${pts[1][1]} L ${pts[2][0]} ${pts[2][1]} Z`;
  return (
    <>
      <path
        d={path} fill="none" stroke={color} strokeWidth="1.1"
        strokeOpacity="0.85" strokeLinejoin="round"
        style={{ filter: `drop-shadow(0 0 2px ${color})` }}
      />
      {pts.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="1.7" fill={color}
          style={{ filter: `drop-shadow(0 0 2px ${color})` }} />
      ))}
    </>
  );
}

function AmberBracket({
  angleDeg, radius, size, color,
}: { angleDeg: number; radius: number; size: number; color: string }) {
  const rad = (angleDeg - 90) * Math.PI / 180;
  const x = Math.cos(rad) * radius;
  const y = Math.sin(rad) * radius;
  return (
    <g transform={`translate(${x} ${y}) rotate(${angleDeg + 90})`}>
      <rect
        x={-size * 1.6} y={-size / 2}
        width={size * 3.2} height={size}
        rx={size / 4}
        fill="none" stroke={color} strokeWidth="0.8" strokeOpacity="0.95"
        style={{ filter: `drop-shadow(0 0 2px ${color})` }}
      />
      <rect
        x={-size * 1.1} y={-size / 4}
        width={size * 2.2} height={size / 2}
        fill={color} fillOpacity="0.35"
      />
    </g>
  );
}
