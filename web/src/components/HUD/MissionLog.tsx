/**
 * MISSION LOG — anticipation feed.
 * Surfaces last actions + JARVIS's next-step suggestion if a tool just landed.
 */
import { useMemo } from "react";
import { useStore } from "../../lib/store";

export default function MissionLog() {
  const tools = useStore((s) => s.tools);
  const chat = useStore((s) => s.chat);

  const items = useMemo(() => {
    const events: Array<{ id: string; ts: number; sev: string; label: string; detail: string }> = [];
    for (const t of tools.slice(-8)) {
      const sev = t.status === "fail" ? "danger" : t.status === "denied" ? "warn" : t.status === "ok" ? "ok" : "cyan";
      events.push({
        id: `t-${t.id}`,
        ts: t.ts,
        sev,
        label: t.tool,
        detail: t.status.toUpperCase() + (t.duration_s ? ` · ${t.duration_s.toFixed(1)}s` : ""),
      });
    }
    for (const c of chat.slice(-3)) {
      if (c.role === "assistant") events.push({ id: `c-${c.id}`, ts: c.ts, sev: "aqua", label: "JARVIS", detail: c.text.slice(0, 56) });
      else if (c.role === "user")  events.push({ id: `c-${c.id}`, ts: c.ts, sev: "cyan", label: "USER",   detail: c.text.slice(0, 56) });
    }
    events.sort((a, b) => b.ts - a.ts);
    return events.slice(0, 6);
  }, [tools, chat]);

  const tone = (s: string) =>
    s === "danger" ? "text-jarvis-danger"
    : s === "warn"   ? "text-jarvis-warn"
    : s === "ok"     ? "text-jarvis-ok"
    : s === "aqua"   ? "text-jarvis-aqua"
    :                 "text-jarvis-cyan";

  return (
    <div className="holo-panel p-2">
      <div className="flex items-center justify-between px-1 pb-1 mb-1 border-b border-jarvis-cyan/20">
        <div className="text-display text-[10px] tracking-[0.3em] text-jarvis-cyan/80">MISSION LOG</div>
        <div className="text-mono text-[9px] text-jarvis-cyan/40">{items.length}</div>
      </div>
      <ul className="space-y-0.5 max-h-40 overflow-hidden">
        {items.length === 0 && (
          <li className="text-mono text-[10px] text-jarvis-cyan/40 italic px-1">No events. Awaiting orders, sir.</li>
        )}
        {items.map((e) => (
          <li key={e.id} className="flex items-baseline gap-2 px-1 text-mono text-[10px] leading-tight">
            <span className="text-jarvis-cyan/30 w-10 shrink-0">
              {new Date(e.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}
            </span>
            <span className={`${tone(e.sev)} w-16 shrink-0 truncate uppercase tracking-wider`}>{e.label}</span>
            <span className="text-jarvis-cyan/60 truncate flex-1">{e.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
