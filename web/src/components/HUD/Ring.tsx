/**
 * Circular gauge ring — SVG. Used for CPU/RAM/Disk diagnostic dial.
 */
interface Props {
  value: number;            // 0..100
  label: string;
  sub?: string;
  size?: number;
  color?: string;
}

export default function Ring({ value, label, sub, size = 110, color = "#22d3ee" }: Props) {
  const v = Math.max(0, Math.min(100, value));
  const r = size / 2 - 8;
  const cx = size / 2;
  const cy = size / 2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - v / 100);
  const accentColor = v > 85 ? "#ef4444" : v > 65 ? "#f59e0b" : color;

  return (
    <div className="relative inline-flex flex-col items-center">
      <svg width={size} height={size} className="-rotate-90">
        {/* Background ring */}
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(34,211,238,0.12)" strokeWidth="3" />
        {/* Tick marks */}
        {Array.from({ length: 40 }).map((_, i) => {
          const ang = (i / 40) * 2 * Math.PI;
          const x1 = cx + (r + 6) * Math.cos(ang);
          const y1 = cy + (r + 6) * Math.sin(ang);
          const x2 = cx + (r + 2) * Math.cos(ang);
          const y2 = cy + (r + 2) * Math.sin(ang);
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(34,211,238,0.3)" strokeWidth="1" />;
        })}
        {/* Value arc */}
        <circle
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke={accentColor}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          style={{ filter: `drop-shadow(0 0 6px ${accentColor})`, transition: "stroke-dashoffset 0.6s ease-out, stroke 0.4s" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div
          className="text-display glow-text leading-none"
          style={{ color: accentColor, fontSize: Math.max(10, size * 0.22) }}
        >
          {v.toFixed(0)}<span style={{ fontSize: Math.max(7, size * 0.12) }}>%</span>
        </div>
        <div
          className="text-mono text-jarvis-cyan/60 uppercase tracking-widest leading-tight"
          style={{ fontSize: Math.max(7, size * 0.10) }}
        >
          {label}
        </div>
        {sub && (
          <div
            className="text-mono text-jarvis-cyan/40 mt-0.5 leading-tight"
            style={{ fontSize: Math.max(7, size * 0.10) }}
          >
            {sub}
          </div>
        )}
      </div>
    </div>
  );
}
