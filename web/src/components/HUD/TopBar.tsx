import { useEffect, useState } from "react";
import { useStore } from "../../lib/store";

export default function TopBar() {
  const [now, setNow] = useState(new Date());
  const health = useStore((s) => s.health);
  const connected = useStore((s) => s.connected);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const date = now.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", year: "numeric" });

  return (
    <div className="absolute top-0 inset-x-0 z-40 pointer-events-none">
      <div className="flex items-center justify-between px-6 py-3">
        {/* ── LEFT — Identity ──────────────────────────────────────── */}
        <div className="pointer-events-auto flex items-center gap-5">
          <div className="flex items-center gap-3">
            <div className="relative">
              <div
                className={`w-2 h-2 rounded-full ${connected ? "bg-jarvis-ok animate-pulse_glow" : "bg-jarvis-danger"}`}
              />
              {connected && (
                <div className="absolute inset-0 w-2 h-2 rounded-full bg-jarvis-ok blur-md opacity-70" />
              )}
            </div>
            <span className="text-display text-[13px] tracking-[0.45em] text-shimmer font-medium">
              J.A.R.V.I.S.
            </span>
            <span className="text-mono text-[10px] text-jarvis-cyan/40 px-1.5 py-0.5 border border-jarvis-cyan/15 rounded-md">
              MK&nbsp;II
            </span>
          </div>
          <div className="hidden md:flex text-mono text-[10.5px] text-jarvis-ice/40 gap-4">
            <Stat label="MODEL" value={health?.model.model ?? "—"} />
            <Stat label="IMG"   value={health?.image_model ?? "—"} />
            <Stat label="PROV"  value={health?.model.provider ?? "—"} />
            <Stat label="TOOLS" value={String(health?.tools ?? 0)} />
            <Stat label="PLUG"  value={String(health?.plugins.length ?? 0)} />
          </div>
        </div>

        {/* ── RIGHT — Clock ────────────────────────────────────────── */}
        <div className="pointer-events-auto flex items-center gap-4">
          <div className="text-mono text-right leading-tight tabular-nums">
            <div className="text-[15px] text-jarvis-ice glow-text tracking-wider">{time}</div>
            <div className="text-[10px] text-jarvis-ice/40 uppercase tracking-[0.2em]">{date}</div>
          </div>
        </div>
      </div>
      {/* Hairline gradient divider */}
      <div className="glass-divider" />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-jarvis-ice/30 uppercase tracking-[0.2em]">{label}</span>
      <span className="text-jarvis-cyan/85">{value}</span>
    </span>
  );
}
