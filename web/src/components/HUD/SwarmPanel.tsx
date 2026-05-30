/**
 * SWARM PANEL — live multi-agent fan-out tracker.
 *
 * Shows the currently-active (or most recent) parallel_tasks run as a
 * vertical stack of subagent cards. Each card streams status + result of
 * its tool call independently. Auto-hides once every run has been
 * dismissed; auto-renders when a new swarm spawns.
 */
import { AnimatePresence, motion } from "framer-motion";
import { useMemo } from "react";
import { useStore, type SwarmSubtask } from "../../lib/store";

const STATUS_COLOR: Record<SwarmSubtask["status"], string> = {
  pending: "rgba(186,230,253,0.45)",
  running: "rgba(125,211,252,0.95)",
  ok:      "rgba(134,239,172,0.95)",
  fail:    "rgba(252,165,165,0.95)",
};

const STATUS_LABEL: Record<SwarmSubtask["status"], string> = {
  pending: "QUEUED",
  running: "RUNNING",
  ok:      "DONE",
  fail:    "FAILED",
};

export default function SwarmPanel() {
  const swarms = useStore((s) => s.swarms);
  const dismiss = useStore((s) => s.dismissSwarm);

  // Most-recent run first; cap to 3 visible.
  const visible = useMemo(() => swarms.slice().reverse().slice(0, 3), [swarms]);

  if (visible.length === 0) return null;

  return (
    <div className="holo-panel flex flex-col h-full overflow-hidden">
      <div className="panel-header flex items-center justify-between gap-2 px-3 py-2 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-display text-[11px] tracking-[0.4em] text-shimmer font-medium">SWARM</span>
          <span className="glass-chip">{swarms.filter((s) => s.active).length} active</span>
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-3">
        <AnimatePresence initial={false}>
          {visible.map((run) => {
            const done = run.tasks.filter((t) => t.status === "ok" || t.status === "fail").length;
            const failed = run.tasks.filter((t) => t.status === "fail").length;
            const pct = run.tasks.length ? (done / run.tasks.length) * 100 : 0;
            return (
              <motion.div
                key={run.id}
                layout
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                className="rounded-xl border overflow-hidden"
                style={{
                  background: "rgba(14,24,42,0.40)",
                  borderColor: run.active
                    ? "rgba(125,211,252,0.40)"
                    : "rgba(186,230,253,0.15)",
                  boxShadow: run.active
                    ? "0 0 24px -6px rgba(125,211,252,0.55), 0 4px 14px -6px rgba(0,0,0,0.5)"
                    : "0 4px 14px -6px rgba(0,0,0,0.5)",
                }}
              >
                {/* Run header */}
                <div className="flex items-center justify-between px-3 py-1.5 border-b border-jarvis-cyan/10">
                  <div className="flex items-center gap-2 text-mono text-[10px] uppercase tracking-[0.2em]">
                    <span className={run.active ? "text-jarvis-aqua animate-pulse" : "text-jarvis-ice/55"}>
                      ⌬ swarm × {run.tasks.length}
                    </span>
                    <span className="text-jarvis-ice/35 tabular-nums">
                      {done}/{run.tasks.length}{failed > 0 ? ` · ${failed} fail` : ""}
                    </span>
                  </div>
                  {!run.active && (
                    <button
                      onClick={() => dismiss(run.id)}
                      className="text-mono text-[10px] text-jarvis-ice/40 hover:text-jarvis-danger transition-colors"
                      title="Dismiss"
                    >
                      ×
                    </button>
                  )}
                </div>

                {/* Progress bar */}
                <div className="relative h-[2px] bg-jarvis-cyan/10 overflow-hidden">
                  <motion.div
                    className="absolute inset-y-0 left-0"
                    style={{
                      background: failed > 0
                        ? "linear-gradient(90deg, #7dd3fc, #fca5a5)"
                        : "linear-gradient(90deg, #7dd3fc, #a5f3fc)",
                      boxShadow: "0 0 12px rgba(125,211,252,0.7)",
                    }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: 0.4, ease: "easeOut" }}
                  />
                </div>

                {/* Subtasks */}
                <div className="divide-y divide-jarvis-cyan/5">
                  {run.tasks.map((t) => (
                    <SubtaskRow key={t.id} t={t} />
                  ))}
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}

function SubtaskRow({ t }: { t: SwarmSubtask }) {
  const elapsed = t.endedAt
    ? ((t.endedAt - t.startedAt) / 1000).toFixed(1)
    : ((Date.now() - t.startedAt) / 1000).toFixed(1);
  return (
    <div className="px-3 py-2 flex flex-col gap-1">
      <div className="flex items-center gap-2 min-w-0">
        <span
          className="w-1.5 h-1.5 rounded-full shrink-0"
          style={{
            background: STATUS_COLOR[t.status],
            boxShadow: `0 0 8px ${STATUS_COLOR[t.status]}`,
          }}
        />
        <span className="text-[12px] text-jarvis-ice font-medium truncate flex-1">
          {t.label}
        </span>
        <span
          className="text-mono text-[8.5px] tracking-[0.18em] uppercase shrink-0"
          style={{ color: STATUS_COLOR[t.status] }}
        >
          {STATUS_LABEL[t.status]}
        </span>
        <span className="text-mono text-[9px] text-jarvis-ice/40 tabular-nums shrink-0">{elapsed}s</span>
      </div>
      {(t.tool || t.preview) && (
        <div className="text-mono text-[10px] text-jarvis-ice/55 pl-3.5 truncate">
          {t.tool && <span className="text-jarvis-cyan/65">{t.tool}</span>}
          {t.tool && t.preview ? " · " : ""}
          {t.preview && <span>{t.preview}</span>}
        </div>
      )}
      {t.status === "fail" && t.result && (
        <div className="text-mono text-[10px] text-jarvis-danger pl-3.5 line-clamp-2">{t.result}</div>
      )}
    </div>
  );
}
