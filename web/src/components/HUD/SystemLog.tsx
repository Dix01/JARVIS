/**
 * SYSTEM LOG — live JARVIS terminal stream neatly tucked in the HUD column.
 *
 * Connects to /api/logs/stream (SSE) and renders a scrollable,
 * level-coloured terminal that auto-scrolls but locks scroll when the
 * user drags up to read history.
 */
import { useEffect, useRef, useState, useCallback } from "react";

interface LogEntry {
  ts: number;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  name: string;
  msg: string;
}

const MAX_LINES = 250;

const LEVEL_COLOR: Record<string, string> = {
  DEBUG:    "text-jarvis-cyan/30",
  INFO:     "text-jarvis-cyan/80",
  WARNING:  "text-jarvis-warn",
  ERROR:    "text-jarvis-danger",
  CRITICAL: "text-red-400",
};

const LEVEL_BADGE: Record<string, string> = {
  DEBUG:    "bg-jarvis-cyan/10 text-jarvis-cyan/40",
  INFO:     "bg-jarvis-cyan/10 text-jarvis-aqua",
  WARNING:  "bg-jarvis-warn/10 text-jarvis-warn",
  ERROR:    "bg-jarvis-danger/10 text-jarvis-danger",
  CRITICAL: "bg-red-900/30 text-red-400",
};

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}:${String(d.getSeconds()).padStart(2,"0")}`;
}

function shortName(name: string): string {
  // "jarvis.mediagen" → "mediagen"
  const parts = name.split(".");
  return parts[parts.length - 1] ?? name;
}

export default function SystemLog() {
  const [logs, setLogs]           = useState<LogEntry[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [connected, setConnected] = useState(false);
  const [filter, setFilter]       = useState<"ALL" | "INFO" | "WARN" | "ERROR">("ALL");
  const bodyRef                   = useRef<HTMLDivElement>(null);
  const bottomRef                 = useRef<HTMLDivElement>(null);
  const autoScroll                = useRef(true);
  const esRef                     = useRef<EventSource | null>(null);

  // ── SSE connection ──────────────────────────────────────────────────────
  useEffect(() => {
    let es: EventSource;
    let retryId: ReturnType<typeof setTimeout>;

    const connect = () => {
      es = new EventSource("/api/logs/stream");
      esRef.current = es;

      es.onopen = () => setConnected(true);

      es.onmessage = (e) => {
        try {
          const entry: LogEntry = JSON.parse(e.data);
          setLogs((prev) => {
            const next = [...prev, entry];
            return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
          });
        } catch {/* ignore malformed */}
      };

      es.onerror = () => {
        setConnected(false);
        es.close();
        retryId = setTimeout(connect, 3000);
      };
    };

    connect();
    return () => {
      clearTimeout(retryId);
      es?.close();
      esRef.current = null;
      setConnected(false);
    };
  }, []);

  // ── Auto-scroll ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (autoScroll.current && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "instant" });
    }
  }, [logs]);

  const handleScroll = useCallback(() => {
    const el = bodyRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    autoScroll.current = atBottom;
  }, []);

  // ── Filtered view ────────────────────────────────────────────────────────
  const visible = logs.filter((l) => {
    if (filter === "ALL")   return true;
    if (filter === "INFO")  return ["INFO", "WARNING", "ERROR", "CRITICAL"].includes(l.level);
    if (filter === "WARN")  return ["WARNING", "ERROR", "CRITICAL"].includes(l.level);
    if (filter === "ERROR") return ["ERROR", "CRITICAL"].includes(l.level);
    return true;
  });

  const clearLogs = () => setLogs([]);

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="holo-panel flex flex-col overflow-hidden"
         style={{ maxHeight: collapsed ? "2.25rem" : "260px", transition: "max-height 0.25s ease" }}>

      {/* Header */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-jarvis-cyan/20 shrink-0">
        <div className="flex items-center gap-1.5">
          {/* Live indicator */}
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${connected ? "bg-jarvis-ok animate-pulse" : "bg-jarvis-danger"}`}
          />
          <span className="text-display text-[10px] tracking-[0.3em] text-jarvis-cyan/80">
            SYS LOG
          </span>
          <span className="text-mono text-[9px] text-jarvis-cyan/35">
            {logs.length}/{MAX_LINES}
          </span>
        </div>

        <div className="flex items-center gap-1">
          {/* Level filter */}
          {!collapsed && (
            <div className="flex gap-0.5">
              {(["ALL","INFO","WARN","ERROR"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`text-mono text-[8px] px-1 py-0.5 rounded tracking-wider transition-colors ${
                    filter === f
                      ? "bg-jarvis-cyan/20 text-jarvis-cyan"
                      : "text-jarvis-cyan/30 hover:text-jarvis-cyan/60"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
          )}

          {/* Clear */}
          {!collapsed && (
            <button
              onClick={clearLogs}
              title="Clear log"
              className="text-mono text-[8px] px-1.5 text-jarvis-cyan/30 hover:text-jarvis-danger transition-colors"
            >
              CLR
            </button>
          )}

          {/* Collapse toggle */}
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="text-mono text-[10px] px-1 text-jarvis-cyan/40 hover:text-jarvis-cyan transition-colors leading-none"
          >
            {collapsed ? "▲" : "▼"}
          </button>
        </div>
      </div>

      {/* Body — scrollable terminal */}
      {!collapsed && (
        <div
          ref={bodyRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto overflow-x-hidden min-h-0"
          style={{ scrollbarWidth: "none" }}
        >
          <div className="px-1.5 py-1 space-y-0.5">
            {visible.length === 0 && (
              <div className="text-mono text-[9px] text-jarvis-cyan/25 text-center py-3">
                {connected ? "awaiting events…" : "connecting…"}
              </div>
            )}
            {visible.map((l, i) => (
              <div key={i} className="flex items-start gap-1 font-mono text-[9px] leading-tight group">
                {/* Timestamp */}
                <span className="text-jarvis-cyan/25 shrink-0 tabular-nums">
                  {fmtTime(l.ts)}
                </span>

                {/* Level badge */}
                <span className={`shrink-0 rounded px-1 leading-tight text-[8px] uppercase tracking-widest ${LEVEL_BADGE[l.level] ?? LEVEL_BADGE.INFO}`}>
                  {l.level === "WARNING" ? "WARN" : l.level.slice(0, 4)}
                </span>

                {/* Logger name */}
                <span className="text-jarvis-cyan/30 shrink-0 max-w-[56px] truncate">
                  {shortName(l.name)}
                </span>

                {/* Message */}
                <span className={`break-all ${LEVEL_COLOR[l.level] ?? "text-jarvis-cyan/60"}`}>
                  {l.msg}
                </span>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        </div>
      )}
    </div>
  );
}
