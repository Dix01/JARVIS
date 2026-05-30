import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { useStore } from "../../lib/store";

const LINES = [
  "INITIALISING J.A.R.V.I.S. KERNEL ...",
  "LINKING NATURAL-LANGUAGE CORE ...",
  "CALIBRATING BRITISH VOICE PROFILE ...",
  "ESTABLISHING SECURE LOCAL UPLINK ...",
  "MOUNTING MEMORY AND MISSION CONTEXT ...",
  "DISCOVERING TOOLS AND AGENT PROTOCOLS ...",
  "ALIGNING HOLOGRAPHIC TELEMETRY ...",
  "RUNNING PRE-FLIGHT DIAGNOSTICS ...",
  "READY.",
];

export default function BootSequence() {
  const booted = useStore((s) => s.booted);
  const setBooted = useStore((s) => s.setBooted);
  const [i, setI] = useState(0);

  useEffect(() => {
    if (booted) return;
    if (i < LINES.length) {
      const t = setTimeout(() => setI(i + 1), 240 + Math.random() * 130);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setBooted(true), 450);
    return () => clearTimeout(t);
  }, [i, booted, setBooted]);

  return (
    <AnimatePresence>
      {!booted && (
        <motion.div
          initial={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.6 }}
          className="fixed inset-0 z-[1000] bg-jarvis-ink flex items-center justify-center vignette"
        >
          <div className="text-center space-y-6">
            <div className="relative w-40 h-40 mx-auto">
              <motion.div
                className="absolute inset-0 rounded-full border-2 border-jarvis-cyan/60"
                animate={{ rotate: 360 }}
                transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
              />
              <motion.div
                className="absolute inset-4 rounded-full border border-jarvis-aqua/50"
                animate={{ rotate: -360 }}
                transition={{ duration: 3, repeat: Infinity, ease: "linear" }}
              />
              <motion.div
                className="absolute inset-12 rounded-full bg-jarvis-cyan/40"
                animate={{ scale: [1, 1.3, 1], opacity: [0.6, 1, 0.6] }}
                transition={{ duration: 1.4, repeat: Infinity }}
              />
              <div className="absolute inset-0 flex items-center justify-center text-display text-jarvis-cyan tracking-widest text-xs glow-text">
                J.A.R.V.I.S.
              </div>
            </div>

            <div className="text-mono text-xs text-jarvis-cyan/70 space-y-1 text-left min-w-[380px]">
              {LINES.slice(0, i).map((line, idx) => (
                <motion.div
                  key={idx}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex items-center gap-2"
                >
                  <span className="text-jarvis-ok">&gt;</span>
                  <span>{line}</span>
                </motion.div>
              ))}
              {i < LINES.length && (
                <div className="flex items-center gap-2 animate-pulse">
                  <span className="text-jarvis-cyan">&gt;</span>
                  <span className="text-jarvis-aqua">{LINES[i]}</span>
                </div>
              )}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
