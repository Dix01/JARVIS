import { useStore } from "../../lib/store";

const STATE_LABELS: Record<string, { label: string; color: string; dot: string }> = {
  idle:      { label: "STANDBY",    color: "text-jarvis-cyan",  dot: "bg-jarvis-cyan"  },
  listening: { label: "LISTENING",  color: "text-jarvis-aqua",  dot: "bg-jarvis-aqua"  },
  thinking:  { label: "ANALYSING",  color: "text-jarvis-violet",dot: "bg-jarvis-violet"},
  speaking:  { label: "RESPONDING", color: "text-jarvis-aqua",  dot: "bg-jarvis-aqua"  },
};

export default function StatusBar() {
  const orb = useStore((s) => s.orbState);
  const audio = useStore((s) => s.audioLevel);
  const connected = useStore((s) => s.connected);
  const tools = useStore((s) => s.tools);
  const voice = useStore((s) => s.voiceProfile);
  const running = tools.filter((t) => t.status === "running").length;

  const info = STATE_LABELS[orb] ?? STATE_LABELS.idle;
  const voiceName = voice?.name
    .replace(/^Microsoft\s+/i, "")
    .replace(/\s*\(.+?\)\s*/g, " ")
    .trim();
  const voiceLabel = voiceName && voiceName.length > 22 ? `${voiceName.slice(0, 21)}...` : voiceName;

  return (
    <div className="absolute bottom-0 inset-x-0 z-40 pointer-events-none">
      <div className="glass-divider mx-6" />
      <div className="flex items-center justify-between px-6 py-2.5 text-mono text-[10px]">
        <div className="flex items-center gap-2">
          <span className={`flex items-center gap-1.5 ${info.color} pointer-events-auto`}>
            <span className="relative flex items-center justify-center">
              <span className={`absolute w-3 h-3 rounded-full ${info.dot} opacity-25 blur-sm`} />
              <span className={`relative w-1.5 h-1.5 rounded-full ${info.dot} animate-pulse`} />
            </span>
            <span className="tracking-[0.3em] glow-text">{info.label}</span>
          </span>
          <Pip label="NET"   value={connected ? "secure" : "down"} valueClass={connected ? "text-jarvis-ok" : "text-jarvis-danger"} />
          <Pip label="TASKS" value={String(running)} />
          <Pip label="VOICE" value={voiceLabel || "calibrating"} />
        </div>
        <div className="flex items-center gap-2 w-56 pointer-events-auto">
          <span className="text-jarvis-ice/35 tracking-[0.25em]">AUD</span>
          <div className="flex-1 h-1.5 bg-jarvis-cyan/[0.06] relative overflow-hidden rounded-full border border-jarvis-cyan/10">
            <div
              className="absolute inset-y-0 left-0 transition-all duration-75 rounded-full"
              style={{
                width: `${Math.min(100, audio * 250)}%`,
                background: "linear-gradient(90deg, rgba(125,211,252,0.9), rgba(167,139,250,0.95))",
                boxShadow: "0 0 10px rgba(125,211,252,0.7), 0 0 20px rgba(167,139,250,0.35)",
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function Pip({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <span className="glass-chip">
      <span className="text-jarvis-ice/40">{label}</span>
      <span className={valueClass || "text-jarvis-ice/85"}>{value}</span>
    </span>
  );
}
