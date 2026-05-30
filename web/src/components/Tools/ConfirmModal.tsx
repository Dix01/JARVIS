import { AnimatePresence, motion } from "framer-motion";
import { useEffect } from "react";
import { useStore } from "../../lib/store";
import { wsClient } from "../../lib/ws";

export default function ConfirmModal() {
  const queue = useStore((s) => s.confirmQueue);
  const pop = useStore((s) => s.popConfirm);
  const top = queue[0];

  useEffect(() => {
    if (!top) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "y") respond(true);
      else if (e.key.toLowerCase() === "n" || e.key === "Escape") respond(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [top?.id]);

  const respond = (approved: boolean) => {
    if (!top) return;
    wsClient.confirm(top.id, approved);
    pop(top.id);
  };

  return (
    <AnimatePresence>
      {top && (
        <motion.div
          key={top.id}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[200] flex items-center justify-center bg-jarvis-ink/80 backdrop-blur-sm"
        >
          <motion.div
            initial={{ scale: 0.94, y: 10 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.94, y: 10 }}
            className="holo-panel max-w-xl w-full mx-4 p-5 relative"
          >
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 bg-jarvis-ink text-display text-[10px] tracking-[0.4em] text-jarvis-cyan border border-jarvis-cyan/40">
              PERMISSION REQUIRED
            </div>
            <div className="flex items-baseline justify-between mb-3">
              <div className="text-display text-jarvis-cyan glow-text text-lg">{top.tool}</div>
              <PermBadge level={top.permission} />
            </div>
            <div className="text-mono text-sm text-jarvis-aqua bg-jarvis-cyan/5 border border-jarvis-cyan/20 p-3 mb-3 break-words">
              {top.preview}
            </div>
            {Object.keys(top.args).length > 0 && (
              <div className="text-mono text-[11px] text-jarvis-cyan/60 mb-3 max-h-32 overflow-y-auto">
                <div className="text-jarvis-cyan/40 mb-1">args:</div>
                <pre className="whitespace-pre-wrap">{JSON.stringify(top.args, null, 2)}</pre>
              </div>
            )}
            <div className="flex gap-2 justify-end pt-2">
              <button
                onClick={() => respond(false)}
                className="px-4 py-2 border border-jarvis-danger/60 text-jarvis-danger text-mono text-xs uppercase tracking-widest hover:bg-jarvis-danger/10 clip-trap"
              >
                Deny <span className="opacity-60">(n)</span>
              </button>
              <button
                onClick={() => respond(true)}
                className="px-4 py-2 border border-jarvis-ok/60 text-jarvis-ok text-mono text-xs uppercase tracking-widest hover:bg-jarvis-ok/10 clip-trap"
              >
                Approve <span className="opacity-60">(y)</span>
              </button>
            </div>
            {queue.length > 1 && (
              <div className="absolute -bottom-3 right-3 px-2 py-0.5 bg-jarvis-ink text-mono text-[10px] text-jarvis-cyan/60 border border-jarvis-cyan/30">
                +{queue.length - 1} queued
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function PermBadge({ level }: { level: string }) {
  const map: Record<string, string> = {
    safe: "border-jarvis-ok/60 text-jarvis-ok bg-jarvis-ok/5",
    caution: "border-jarvis-warn/60 text-jarvis-warn bg-jarvis-warn/5",
    dangerous: "border-jarvis-danger/60 text-jarvis-danger bg-jarvis-danger/10 animate-pulse_glow",
  };
  return (
    <div className={`text-mono text-[10px] uppercase tracking-widest px-2 py-0.5 border ${map[level] || map.caution}`}>
      {level}
    </div>
  );
}
