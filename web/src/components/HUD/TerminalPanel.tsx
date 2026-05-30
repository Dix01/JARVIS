/**
 * TERMINAL PANEL — live SSE log stream, premium glass.
 */
import { useCallback, useEffect, useRef, useState } from "react";

interface LogEntry {
  ts: number;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
  name: string;
  msg: string;
}

const MAX_LINES = 400;

const LEVEL_COLOR: Record<string, string> = {
  DEBUG:    "text-jarvis-ice/35",
  INFO:     "text-jarvis-ice/80",
  WARNING:  "text-amber-300",
  ERROR:    "text-rose-400",
  CRITICAL: "text-rose-300",
};

const LEVEL_DOT: Record<string, string> = {
  DEBUG:    "bg-jarvis-ice/25",
  INFO:     "bg-jarvis-cyan",
  WARNING:  "bg-amber-400",
  ERROR:    "bg-rose-500",
  CRITICAL: "bg-rose-400 animate-pulse",
};

type FilterLevel = "ALL" | "INFO" | "WARN" | "ERR";

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function shortName(name: string): string {
  const parts = name.split(".");
  return parts[parts.length - 1] ?? name;
}

function passFilter(l: LogEntry, f: FilterLevel): boolean {
  if (f === "ALL") return true;
  if (f === "INFO") return ["INFO", "WARNING", "ERROR", "CRITICAL"].includes(l.level);
  if (f === "WARN") return ["WARNING", "ERROR", "CRITICAL"].includes(l.level);
  if (f === "ERR")  return ["ERROR", "CRITICAL"].includes(l.level);
  return true;
}

export default function TerminalPanel() {
  const [logs, setLogs]      = useState<LogEntry[]>([]);
  const [connected, setConn] = useState(false);
  const [filter, setFilter]  = useState<FilterLevel>("ALL");

  const bodyRef    = useRef<HTMLDivElement>(null);
  const bottomRef  = useRef<HTMLDivElement>(null);
  const autoScroll = useRef(true);

  useEffect(() => {
    let es: EventSource;
    let retryId: ReturnType<typeof setTimeout>;
    const connect = () => {
      es = new EventSource("/api/logs/stream");
      es.onopen  = () => setConn(true);
      es.onmessage = (e) => {
        try {
          const entry: LogEntry = JSON.parse(e.data);
          setLogs((prev) => {
            const next = [...prev, entry];
            return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
          });
        } catch {/* ignore */}
      };
      es.onerror = () => {
        setConn(false);
        es.close();
        retryId = setTimeout(connect, 3000);
      };
    };
    connect();
    return () => { clearTimeout(retryId); es?.close(); setConn(false); };
  }, []);

  useEffect(() => {
    if (autoScroll.current && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "instant" });
    }
  }, [logs]);

  const handleScroll = useCallback(() => {
    const el = bodyRef.current; if (!el) return;
    autoScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }, []);

  const visible = logs.filter((l) => passFilter(l, filter));

  return (
    <div className="holo-panel flex flex-col flex-1 min-h-0 overflow-hidden">
      {/* Header */}
      <div className="panel-header flex items-center justify-between gap-2 px-3 py-2 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-mono text-[10px] text-jarvis-cyan/80 font-bold">›_</span>
          <span className="text-display text-[10px] tracking-[0.4em] text-shimmer font-medium">TERMINAL</span>
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${connected ? "bg-jarvis-ok animate-pulse" : "bg-jarvis-danger"}`} />
          <span className="text-mono text-[9px] text-jarvis-ice/35 tabular-nums">{visible.length}</span>
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          {(["ALL", "INFO", "WARN", "ERR"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`text-mono text-[9px] px-1.5 py-0.5 rounded-md tracking-[0.15em] transition-all ${
                filter === f
                  ? "bg-jarvis-cyan/15 text-jarvis-ice border border-jarvis-cyan/25"
                  : "text-jarvis-ice/35 hover:text-jarvis-ice/80 border border-transparent"
              }`}
            >
              {f}
            </button>
          ))}
          <button
            onClick={() => setLogs([])}
            title="Clear"
            className="text-mono text-[9px] px-1.5 py-0.5 rounded-md text-jarvis-ice/35 hover:text-jarvis-danger transition-colors"
          >
            ×
          </button>
        </div>
      </div>

      {/* Body */}
      <div
        ref={bodyRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto overflow-x-hidden min-h-0 px-3 py-2 space-y-0.5"
      >
        {visible.length === 0 ? (
          <div className="flex items-center gap-2 text-mono text-[10px] text-jarvis-ice/30 mt-2">
            <span className="animate-pulse">▮</span>
            <span>{connected ? "awaiting events…" : "connecting…"}</span>
          </div>
        ) : (
          visible.map((l, i) => (
            <div key={i} className="flex items-start gap-1.5 font-mono text-[10px] leading-[1.35] min-w-0">
              <span className="text-jarvis-ice/30 shrink-0 tabular-nums text-[9.5px] mt-0.5">{fmtTime(l.ts)}</span>
              <span className={`mt-1.5 shrink-0 w-1 h-1 rounded-full ${LEVEL_DOT[l.level] ?? "bg-jarvis-ice/30"}`} />
              <span className="shrink-0 text-jarvis-cyan/60 text-[9.5px] w-14 truncate" title={l.name}>
                {shortName(l.name)}
              </span>
              <span className={`flex-1 min-w-0 break-words ${LEVEL_COLOR[l.level] ?? "text-jarvis-ice/70"}`}>{l.msg}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
