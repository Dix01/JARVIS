/**
 * SUBSYSTEMS — suit health stack. Premium glass rows.
 */
import { useStore } from "../../lib/store";

interface Row { key: string; label: string; pct: number; status: "ok" | "warn" | "crit" | "off"; sub: string }

export default function Subsystems() {
  const stats = useStore((s) => s.stats);
  const health = useStore((s) => s.health);
  const tools = useStore((s) => s.tools);
  const connected = useStore((s) => s.connected);

  const sev = (pct: number): Row["status"] => pct >= 90 ? "crit" : pct >= 75 ? "warn" : "ok";

  const rows: Row[] = [];
  if (stats) {
    rows.push({ key: "cpu", label: "PROCESSOR",  pct: stats.cpu,           status: sev(stats.cpu),           sub: `${stats.cpu_count} cores` });
    rows.push({ key: "ram", label: "MEMORY",     pct: stats.ram.percent,   status: sev(stats.ram.percent),   sub: `${stats.ram.used_gb.toFixed(1)}/${stats.ram.total_gb.toFixed(0)} GB` });
    rows.push({ key: "dsk", label: "STORAGE",    pct: stats.disk.percent,  status: sev(stats.disk.percent),  sub: `${(stats.disk.total_gb - stats.disk.used_gb).toFixed(0)} GB free` });
    if (stats.gpu?.available) {
      const load = stats.gpu.load_percent ?? 0;
      const tempStr = typeof stats.gpu.temp_c === "number" ? ` · ${stats.gpu.temp_c.toFixed(0)}°C` : "";
      rows.push({
        key: "gpu",
        label: "GPU",
        pct: load,
        status: sev(load),
        sub: `${(stats.gpu.name || "GPU").slice(0, 22)}${tempStr}`,
      });
    }
    if (stats.battery) {
      const bp = stats.battery.percent;
      rows.push({ key: "pwr", label: "POWER", pct: bp, status: bp < 20 ? "crit" : bp < 40 ? "warn" : "ok", sub: stats.battery.plugged ? "GRID-LINKED" : "RESERVE" });
    } else {
      rows.push({ key: "pwr", label: "POWER", pct: 100, status: "ok", sub: "GRID-LINKED" });
    }
  }
  rows.push({
    key: "lnk",
    label: "DATA LINK",
    pct: connected ? 100 : 0,
    status: connected ? "ok" : "crit",
    sub: connected ? "SECURE" : "DOWN",
  });
  rows.push({
    key: "ai",
    label: "COGNITION",
    pct: health ? 100 : 0,
    status: health ? "ok" : "off",
    sub: health?.model.model ? health.model.model.slice(0, 22) : "OFFLINE",
  });
  const running = tools.filter((t) => t.status === "running").length;
  rows.push({
    key: "tools",
    label: "TOOL BUS",
    pct: Math.min(100, 30 + running * 18),
    status: running > 3 ? "warn" : "ok",
    sub: `${health?.tools ?? 0} armed · ${running} active`,
  });

  return (
    <div className="holo-panel flex flex-col overflow-hidden">
      <div className="panel-header flex items-center justify-between px-3.5 py-2 shrink-0">
        <span className="text-display text-[10px] tracking-[0.4em] text-shimmer font-medium">SUBSYSTEMS</span>
        <span className="glass-chip">{rows.length}</span>
      </div>
      <ul className="p-3 space-y-2 overflow-y-auto min-h-0">
        {rows.map((r) => {
          const tone =
            r.status === "crit" ? "text-jarvis-danger"
            : r.status === "warn" ? "text-jarvis-warn"
            : r.status === "off"  ? "text-jarvis-ice/40"
            :                       "text-jarvis-ok";
          const barGrad =
            r.status === "crit" ? "linear-gradient(90deg, rgba(251,113,133,0.95), rgba(251,113,133,0.6))"
            : r.status === "warn" ? "linear-gradient(90deg, rgba(251,191,36,0.95), rgba(251,191,36,0.6))"
            : r.status === "off"  ? "linear-gradient(90deg, rgba(186,230,253,0.3), rgba(186,230,253,0.15))"
            :                       "linear-gradient(90deg, rgba(125,211,252,0.95), rgba(167,139,250,0.7))";
          return (
            <li key={r.key} className="min-w-0">
              <div className="flex items-center justify-between gap-2 min-w-0">
                <span className="text-mono text-[10px] text-jarvis-ice/80 tracking-[0.15em] truncate min-w-0">{r.label}</span>
                <span className={`text-mono text-[9px] uppercase tracking-[0.2em] shrink-0 ${tone}`}>{r.status}</span>
              </div>
              <div className="flex items-center gap-2 mt-1">
                <div className="flex-1 h-1 rounded-full overflow-hidden bg-jarvis-ice/[0.06] min-w-0">
                  <div
                    className="h-full rounded-full transition-all duration-300"
                    style={{
                      width: `${r.pct}%`,
                      background: barGrad,
                      boxShadow: "0 0 10px rgba(125,211,252,0.45)",
                    }}
                  />
                </div>
                <span className="text-mono text-[9px] text-jarvis-ice/55 w-9 text-right tabular-nums shrink-0">
                  {r.pct.toFixed(0)}%
                </span>
              </div>
              <div className="text-mono text-[9px] text-jarvis-ice/40 mt-0.5 truncate" title={r.sub}>
                {r.sub}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
