/**
 * ARC REACTOR — sleeker concentric reactor with energy flow.
 * Pulses with orb state + tracks CPU load.
 */
import { useStore } from "../../lib/store";

export default function ArcReactor() {
  const orb = useStore((s) => s.orbState);
  const cpu = useStore((s) => s.stats?.cpu ?? 0);
  const ram = useStore((s) => s.stats?.ram.percent ?? 0);
  const intensity = orb === "thinking" || orb === "speaking" ? 1 : 0.7;

  return (
    <div className="relative w-14 h-14 shrink-0">
      {/* Outer dashed rotation ring */}
      <svg viewBox="0 0 56 56" className="absolute inset-0 animate-spin_slow">
        <circle cx="28" cy="28" r="26" fill="none" stroke="rgba(34,211,238,0.45)" strokeWidth="0.6" strokeDasharray="2 3" />
      </svg>
      {/* Energy gauge ring (CPU) */}
      <svg viewBox="0 0 56 56" className="absolute inset-0">
        <circle cx="28" cy="28" r="22" fill="none" stroke="rgba(34,211,238,0.12)" strokeWidth="1.4" />
        <circle
          cx="28" cy="28" r="22"
          fill="none" stroke="#22d3ee" strokeWidth="1.4"
          strokeLinecap="round" strokeDasharray={`${(cpu / 100) * 138} 138`}
          transform="rotate(-90 28 28)"
          style={{ filter: "drop-shadow(0 0 4px rgba(34,211,238,0.7))" }}
        />
      </svg>
      {/* Inner counter-rotating ring (RAM) */}
      <svg viewBox="0 0 56 56" className="absolute inset-0 animate-spin_rev">
        <circle cx="28" cy="28" r="17" fill="none" stroke="rgba(103,232,249,0.25)" strokeWidth="0.6" strokeDasharray="1 4" />
        <circle
          cx="28" cy="28" r="17"
          fill="none" stroke="#67e8f9" strokeWidth="0.9"
          strokeLinecap="round" strokeDasharray={`${(ram / 100) * 107} 107`}
          transform="rotate(-90 28 28)"
        />
      </svg>
      {/* Core triskelion */}
      <svg viewBox="0 0 56 56" className="absolute inset-0">
        <g
          style={{
            transformOrigin: "28px 28px",
            animation: "spin_slow 12s linear infinite",
            filter: `drop-shadow(0 0 ${4 + intensity * 4}px rgba(34,211,238,${0.6 + intensity * 0.3}))`,
          }}
        >
          {Array.from({ length: 3 }).map((_, i) => (
            <path
              key={i}
              d="M28 28 L34 18 A12 12 0 0 1 39 24 Z"
              fill="rgba(34,211,238,0.85)"
              transform={`rotate(${i * 120} 28 28)`}
            />
          ))}
          <circle cx="28" cy="28" r="4.5" fill="#67e8f9" />
          <circle cx="28" cy="28" r="2" fill="#ffffff" opacity="0.9" />
        </g>
      </svg>
      {/* Tick marks — 12 cardinal */}
      {Array.from({ length: 12 }).map((_, i) => (
        <div
          key={i}
          className="absolute w-px h-1.5 bg-jarvis-cyan/60"
          style={{
            top: "1px",
            left: "50%",
            transformOrigin: "50% 27px",
            transform: `translateX(-50%) rotate(${i * 30}deg)`,
          }}
        />
      ))}
    </div>
  );
}
