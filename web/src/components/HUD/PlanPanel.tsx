/**
 * PLAN PANEL — live checklist for an autonomous multi-step task.
 *
 * When the orchestrator drafts a plan for a complex request it streams the
 * steps here. Each step checks itself off as the matching tool resolves, the
 * active step pulses, and the whole panel settles to a calm "complete" state
 * once the turn finishes. Purely a status surface — no controls beyond dismiss.
 */
import { AnimatePresence, motion } from "framer-motion";
import { useStore } from "../../lib/store";

export default function PlanPanel() {
  const plan = useStore((s) => s.plan);
  const clearPlan = useStore((s) => s.clearPlan);

  if (!plan || plan.steps.length === 0) return null;

  const total = plan.steps.length;
  const done = Math.min(plan.done, total);
  const pct = total ? (done / total) * 100 : 0;
  const activeIdx = plan.complete ? -1 : done;

  return (
    <div className="holo-panel flex flex-col h-full overflow-hidden">
      <div className="panel-header flex items-center justify-between gap-2 px-3 py-2 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-display text-[11px] tracking-[0.4em] text-shimmer font-medium">
            PLAN
          </span>
          <span className="glass-chip tabular-nums">
            {done}/{total}
          </span>
          {!plan.complete && (
            <span className="text-mono text-[9px] tracking-[0.2em] uppercase text-jarvis-aqua animate-pulse">
              executing
            </span>
          )}
        </div>
        {plan.complete && (
          <button
            onClick={clearPlan}
            className="text-mono text-[10px] text-jarvis-ice/40 hover:text-jarvis-danger transition-colors"
            title="Dismiss"
          >
            ×
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div className="relative h-[2px] bg-jarvis-cyan/10 overflow-hidden shrink-0">
        <motion.div
          className="absolute inset-y-0 left-0"
          style={{
            background: plan.complete
              ? "linear-gradient(90deg, #7dd3fc, #86efac)"
              : "linear-gradient(90deg, #7dd3fc, #a5f3fc)",
            boxShadow: "0 0 12px rgba(125,211,252,0.7)",
          }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-1.5">
        <AnimatePresence initial={false}>
          {plan.steps.map((step, i) => {
            const checked = i < done;
            const active = i === activeIdx;
            return (
              <motion.div
                key={i}
                layout
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: checked || active ? 1 : 0.5, x: 0 }}
                transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                className="flex items-start gap-2.5 py-1"
              >
                <StepDot checked={checked} active={active} />
                <span
                  className="text-[12px] leading-snug flex-1"
                  style={{
                    color: checked
                      ? "rgba(134,239,172,0.92)"
                      : active
                      ? "rgba(213,244,255,0.95)"
                      : "rgba(186,230,253,0.6)",
                    textDecoration: checked ? "none" : "none",
                  }}
                >
                  {step}
                </span>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}

function StepDot({ checked, active }: { checked: boolean; active: boolean }) {
  if (checked) {
    return (
      <span
        className="mt-0.5 w-4 h-4 rounded-full shrink-0 flex items-center justify-center text-[9px] font-bold"
        style={{
          background: "rgba(134,239,172,0.18)",
          border: "1px solid rgba(134,239,172,0.7)",
          color: "rgba(134,239,172,0.95)",
          boxShadow: "0 0 10px rgba(134,239,172,0.45)",
        }}
      >
        ✓
      </span>
    );
  }
  return (
    <span
      className={`mt-0.5 w-4 h-4 rounded-full shrink-0 border ${active ? "animate-pulse" : ""}`}
      style={{
        borderColor: active ? "rgba(125,211,252,0.95)" : "rgba(186,230,253,0.3)",
        background: active ? "rgba(125,211,252,0.15)" : "transparent",
        boxShadow: active ? "0 0 10px rgba(125,211,252,0.6)" : "none",
      }}
    />
  );
}
