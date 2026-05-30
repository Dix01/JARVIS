import { useStore, type ToolCall } from "../../lib/store";
import { motion, AnimatePresence } from "framer-motion";

export default function ToolFeed() {
  const tools = useStore((s) => s.tools);
  const recent = [...tools].reverse().slice(0, 8);

  return (
    <div className="holo-panel p-2 flex flex-col">
      <Header />
      <div className="space-y-1.5 overflow-y-auto max-h-[40vh] pr-1">
        {recent.length === 0 ? (
          <div className="text-mono text-[11px] text-jarvis-cyan/40 px-1 py-2">no tool activity</div>
        ) : (
          <AnimatePresence initial={false}>
            {recent.map((t) => <Card key={t.id} t={t} />)}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}

function Header() {
  return (
    <div className="flex items-center justify-between px-1 pb-1 mb-1 border-b border-jarvis-cyan/20">
      <div className="text-display text-[10px] tracking-[0.3em] text-jarvis-cyan/80">TOOL FEED</div>
      <div className="text-mono text-[9px] text-jarvis-cyan/40">live</div>
    </div>
  );
}

function Card({ t }: { t: ToolCall }) {
  const color =
    t.status === "ok"      ? "border-jarvis-ok/60   text-jarvis-ok"      :
    t.status === "fail"    ? "border-jarvis-danger/60 text-jarvis-danger" :
    t.status === "running" ? "border-jarvis-warn/60 text-jarvis-warn"   :
    t.status === "denied"  ? "border-jarvis-danger/40 text-jarvis-danger/70" :
                             "border-jarvis-cyan/40 text-jarvis-cyan";
  const icon =
    t.status === "ok"      ? "✓" :
    t.status === "fail"    ? "✗" :
    t.status === "running" ? "▶" :
    t.status === "denied"  ? "⊘" : "○";
  const perm =
    t.permission === "dangerous" ? "text-jarvis-danger" :
    t.permission === "caution"   ? "text-jarvis-warn"   :
                                    "text-jarvis-ok";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 30 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -30 }}
      transition={{ duration: 0.25 }}
      className={`border-l-2 ${color} bg-jarvis-cyan/[0.03] px-2 py-1.5 text-[11px] text-mono`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className={t.status === "running" ? "animate-pulse" : ""}>{icon}</span>
          <span className="truncate text-jarvis-cyan font-medium">{t.tool}</span>
          <span className={`text-[9px] uppercase tracking-widest ${perm}`}>[{t.permission}]</span>
        </div>
        {t.duration_s != null && (
          <span className="text-jarvis-cyan/40 text-[9px]">{t.duration_s.toFixed(2)}s</span>
        )}
      </div>
      {t.preview && (
        <div className="text-jarvis-cyan/60 truncate text-[10px] mt-0.5">{t.preview}</div>
      )}
      {t.result && t.status !== "running" && (
        <div className="text-jarvis-cyan/50 text-[10px] mt-1 max-h-20 overflow-y-auto whitespace-pre-wrap border-l border-jarvis-cyan/20 pl-2">
          {t.result.slice(0, 600)}{t.result.length > 600 ? "…" : ""}
        </div>
      )}
    </motion.div>
  );
}
