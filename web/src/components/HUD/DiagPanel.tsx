import { useEffect } from "react";
import { useStore } from "../../lib/store";
import { getStats } from "../../lib/api";
import Ring from "./Ring";
import ArcReactor from "./ArcReactor";

export default function DiagPanel() {
  const stats = useStore((s) => s.stats);
  const setStats = useStore((s) => s.setStats);

  useEffect(() => {
    let live = true;
    const tick = async () => {
      try {
        const s = await getStats();
        if (live) setStats(s);
      } catch {/* ignore */}
    };
    tick();
    const id = setInterval(tick, 1500);
    return () => { live = false; clearInterval(id); };
  }, [setStats]);

  if (!stats) {
    return (
      <div className="holo-panel p-3 text-center text-mono text-xs text-jarvis-cyan/50">
        acquiring telemetry…
      </div>
    );
  }

  const gpuAvailable = !!stats.gpu?.available;
  const gpuLoad = stats.gpu?.load_percent ?? 0;
  const gpuMem  = stats.gpu?.mem_percent  ?? 0;

  return (
    <div className="holo-panel p-2 space-y-2">
      <div className="flex items-center justify-between px-1 pb-1 border-b border-jarvis-cyan/20">
        <div className="text-display text-[10px] tracking-[0.3em] text-jarvis-cyan/80">DIAGNOSTICS</div>
        <ArcReactor />
      </div>

      <div className="grid grid-cols-2 gap-1 justify-items-center">
        <Ring value={stats.cpu}          label="CPU"  sub={`${stats.cpu_count}c`}                                size={64} />
        <Ring value={stats.ram.percent}  label="RAM"  sub={`${stats.ram.used_gb.toFixed(1)}g`}                    size={64} />
        <Ring value={stats.disk.percent} label="DISK" sub={`${(stats.disk.total_gb - stats.disk.used_gb).toFixed(0)}g`} size={64} />
        {gpuAvailable ? (
          <Ring
            value={gpuLoad}
            label="GPU"
            sub={`${(stats.gpu?.mem_used_gb ?? 0).toFixed(1)}/${(stats.gpu?.mem_total_gb ?? 0).toFixed(0)}g`}
            size={64}
          />
        ) : (
          <Ring value={0} label="GPU" sub="n/a" size={64} />
        )}
      </div>

      {gpuAvailable && (
        <div className="text-mono text-[9px] text-jarvis-cyan/60 truncate px-1">
          <span className="text-jarvis-cyan/40">GPU</span>{" "}
          <span className="text-jarvis-cyan">{stats.gpu?.name || "—"}</span>
          {typeof stats.gpu?.temp_c === "number" && (
            <> · <span className="text-jarvis-aqua">{stats.gpu?.temp_c?.toFixed(0)}°C</span></>
          )}
          <> · <span className="text-jarvis-cyan">VRAM {gpuMem.toFixed(0)}%</span></>
        </div>
      )}

      <div className="grid grid-cols-2 gap-1 text-mono text-[9px] text-jarvis-cyan/70">
        <Cell k="NET ↑" v={`${stats.net.sent_mb.toFixed(1)} MB`} />
        <Cell k="NET ↓" v={`${stats.net.recv_mb.toFixed(1)} MB`} />
        {stats.battery && (
          <Cell
            k={stats.battery.plugged ? "POWER" : "BATTERY"}
            v={`${stats.battery.percent.toFixed(0)}%${stats.battery.plugged ? "+" : ""}`}
          />
        )}
        <Cell k="HOST" v={stats.os.node} className="truncate" />
      </div>
    </div>
  );
}

function Cell({ k, v, className = "" }: { k: string; v: string; className?: string }) {
  return (
    <div className="border-l border-jarvis-cyan/30 pl-1.5">
      <div className="text-jarvis-cyan/40">{k}</div>
      <div className={`text-jarvis-cyan ${className}`}>{v}</div>
    </div>
  );
}
