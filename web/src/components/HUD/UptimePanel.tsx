import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../../lib/store";

function formatDuration(totalSeconds: number) {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(safeSeconds / 86_400);
  const hours = Math.floor((safeSeconds % 86_400) / 3_600);
  const minutes = Math.floor((safeSeconds % 3_600) / 60);
  const seconds = safeSeconds % 60;

  if (days > 0) {
    return `${days}d ${hours}h ${minutes}m`;
  }

  return [hours, minutes, seconds].map((n) => String(n).padStart(2, "0")).join(":");
}

function formatTime(value: Date) {
  return value.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function formatDateTime(value: Date) {
  return value.toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function UptimePanel() {
  const connected = useStore((s) => s.connected);
  const booted = useStore((s) => s.booted);
  const startedAt = useRef(performance.timeOrigin || Date.now()).current;
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const snapshot = useMemo(() => {
    const uptimeSeconds = (now - startedAt) / 1000;

    return {
      source: connected ? "LINKED" : booted ? "HUD" : "BOOT",
      uptime: formatDuration(uptimeSeconds),
      start: formatDateTime(new Date(startedAt)),
      local: formatTime(new Date(now)),
    };
  }, [booted, connected, now, startedAt]);

  return (
    <div className="holo-panel flex h-full flex-col overflow-hidden">
      <div className="panel-header flex items-center justify-between px-3.5 py-2 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="relative flex h-1.5 w-1.5 shrink-0">
            <span className="absolute inline-flex h-full w-full rounded-full bg-jarvis-aqua opacity-40 animate-ping" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-jarvis-aqua" />
          </span>
          <span className="text-display text-[10px] tracking-[0.35em] text-shimmer font-medium">
            UPTIME
          </span>
        </div>
        <span className="glass-chip">{snapshot.source}</span>
      </div>

      <div className="flex min-h-0 flex-1 flex-col justify-between gap-3 p-3 text-mono">
        <div>
          <div className="text-[9px] uppercase tracking-[0.28em] text-jarvis-cyan/45">
            online duration
          </div>
          <div className="mt-1 text-[24px] leading-none text-jarvis-ice tabular-nums glow-text">
            {snapshot.uptime}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 text-[9px]">
          <Metric label="Start" value={snapshot.start} />
          <Metric label="Local" value={snapshot.local} />
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 border-l border-jarvis-cyan/30 pl-1.5">
      <div className="uppercase tracking-[0.2em] text-jarvis-cyan/40">{label}</div>
      <div className="truncate text-jarvis-cyan" title={value}>
        {value}
      </div>
    </div>
  );
}
