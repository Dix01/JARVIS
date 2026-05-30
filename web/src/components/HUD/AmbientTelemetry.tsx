/**
 * AMBIENT TELEMETRY — UTC, local, uptime, latency, frame rate, wake state.
 * Cheap continuous awareness — the "weather check + ATC check" widget.
 */
import { useEffect, useRef, useState } from "react";
import { useStore } from "../../lib/store";

function useNow() {
  const [n, setN] = useState(new Date());
  useEffect(() => { const id = setInterval(() => setN(new Date()), 1000); return () => clearInterval(id); }, []);
  return n;
}

function useFPS() {
  const [fps, setFps] = useState(0);
  useEffect(() => {
    let raf = 0, frames = 0, last = performance.now();
    const loop = () => {
      frames++;
      const now = performance.now();
      if (now - last >= 1000) {
        setFps(frames);
        frames = 0; last = now;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);
  return fps;
}

function useLatency() {
  const [ms, setMs] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    const ping = async () => {
      const t = performance.now();
      try {
        await fetch("/api/health", { cache: "no-store" });
        if (live) setMs(Math.round(performance.now() - t));
      } catch {
        if (live) setMs(null);
      }
    };
    ping();
    const id = setInterval(ping, 4000);
    return () => { live = false; clearInterval(id); };
  }, []);
  return ms;
}

export default function AmbientTelemetry() {
  const now = useNow();
  const fps = useFPS();
  const latency = useLatency();
  const start = useRef(Date.now()).current;
  const uptimeSec = Math.floor((Date.now() - start) / 1000);
  const uptime = `${String(Math.floor(uptimeSec / 3600)).padStart(2, "0")}:${String(Math.floor((uptimeSec % 3600) / 60)).padStart(2, "0")}:${String(uptimeSec % 60).padStart(2, "0")}`;

  const utc = now.toISOString().slice(11, 19);
  const local = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;

  const orb = useStore((s) => s.orbState);
  const wake = useStore((s) => s.wakeEnabled);
  const mic = useStore((s) => s.micEnabled);

  return (
    <div className="holo-panel p-2">
      <div className="flex items-center justify-between px-1 pb-1 mb-1 border-b border-jarvis-cyan/20">
        <div className="text-display text-[10px] tracking-[0.3em] text-jarvis-cyan/80">AMBIENT</div>
        <div className="text-mono text-[9px] text-jarvis-cyan/40">LIVE</div>
      </div>
      <div className="grid grid-cols-2 gap-1 text-mono text-[9px]">
        <Cell k="LOCAL" v={local} sub={tz.slice(-20)} />
        <Cell k="UTC" v={utc} sub="Z" />
        <Cell k="UPTIME" v={uptime} sub="session" />
        <Cell k="LINK" v={latency !== null ? `${latency} ms` : "—"} sub={latency === null ? "down" : latency < 60 ? "secure" : "lag"} tone={latency === null ? "danger" : latency > 200 ? "warn" : "ok"} />
        <Cell k="FRAME" v={`${fps} fps`} sub={fps < 30 ? "throttled" : "fluid"} tone={fps < 30 ? "warn" : "cyan"} />
        <Cell k="STATE" v={orb.toUpperCase()} sub={mic ? (wake ? "WAKE+MIC" : "MIC ON") : "PASSIVE"} />
      </div>
    </div>
  );
}

function Cell({ k, v, sub, tone = "cyan" }: { k: string; v: string; sub: string; tone?: "cyan" | "ok" | "warn" | "danger" }) {
  const c =
    tone === "ok"     ? "text-jarvis-ok"
    : tone === "warn"   ? "text-jarvis-warn"
    : tone === "danger" ? "text-jarvis-danger"
    :                     "text-jarvis-cyan";
  return (
    <div className="border-l border-jarvis-cyan/30 pl-1.5">
      <div className="text-jarvis-cyan/40">{k}</div>
      <div className={c}>{v}</div>
      <div className="text-jarvis-cyan/30 truncate">{sub}</div>
    </div>
  );
}
