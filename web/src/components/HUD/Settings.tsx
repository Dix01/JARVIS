/**
 * SETTINGS PANEL — in-app config without editing config.yaml.
 *
 * Covers the controls most users actually want to flip: voice on/off,
 * wake-word capture, persona/agent, permission mode, FLUX preload, panel
 * layout reset, full state wipe. Read-only mirrors of server health are
 * shown for context. Anything that requires a backend restart is flagged.
 */
import { useEffect, useState } from "react";
import { useStore } from "../../lib/store";
import { resetAllLayouts } from "./Floating";

export default function Settings() {
  const health = useStore((s) => s.health);
  const voiceEnabled = useStore((s) => s.voiceEnabled);
  const setVoiceEnabled = useStore((s) => s.setVoiceEnabled);
  const wakeEnabled = useStore((s) => s.wakeEnabled);
  const setWakeEnabled = useStore((s) => s.setWakeEnabled);
  const bargeIn = useStore((s) => s.bargeIn);
  const setBargeIn = useStore((s) => s.setBargeIn);
  const clearChat = useStore((s) => s.clearChat);
  const clearMedia = useStore((s) => s.clearMedia);
  const clearTools = useStore((s) => s.clearTools);
  const setReader = useStore((s) => s.setReader);
  const prevSessionAvailable = useStore((s) => s.prevSessionAvailable);
  const restoreLastSession = useStore((s) => s.restoreLastSession);

  const [agents, setAgents] = useState<string[]>([]);
  useEffect(() => {
    fetch("/api/agents")
      .then((r) => r.json())
      .then((j) => setAgents(j?.agents || []))
      .catch(() => undefined);
  }, []);

  const cleanSlate = async () => {
    if (!confirm("Wipe all chat, media, and tool history? Backend memory is preserved.")) return;
    clearChat();
    clearMedia();
    clearTools();
    setReader(null);
    try { await fetch("/api/cleanslate", { method: "POST" }); } catch { /* noop */ }
  };

  return (
    <div className="holo-panel flex flex-col h-full overflow-hidden">
      <div className="panel-header flex items-center justify-between px-3 py-2 shrink-0">
        <span className="text-display text-[11px] tracking-[0.4em] text-shimmer">SETTINGS</span>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-5 text-mono text-[12px] text-jarvis-ice/85">
        {prevSessionAvailable && (
          <Section title="SESSION">
            <div className="text-[10px] text-jarvis-ice/45 pb-1">
              A previous session was kept aside on launch. Memory is always preserved.
            </div>
            <ButtonRow label="Restore previous session" onClick={() => restoreLastSession()} />
          </Section>
        )}

        <Section title="VOICE">
          <Toggle
            label="JARVIS speaks aloud (TTS)"
            value={voiceEnabled}
            onChange={setVoiceEnabled}
          />
          <Toggle
            label="Listen for wake word (mic always on)"
            value={wakeEnabled}
            onChange={setWakeEnabled}
          />
          <Toggle
            label="Say “cancel” to stop JARVIS speaking"
            value={bargeIn}
            onChange={setBargeIn}
          />
        </Section>

        <Section title="DISPLAY">
          <ButtonRow
            label="Reset panel layout"
            danger={false}
            onClick={() => { if (confirm("Reset all panel positions?")) resetAllLayouts(); }}
          />
        </Section>

        <Section title="SYSTEM">
          <KV k="Model"        v={`${health?.model.provider || "—"}/${health?.model.model || "—"}`} />
          <KV k="Image model"  v={health?.image_model || "—"} />
          <KV k="Permissions"  v={health?.permission_mode || "—"} />
          <KV k="Tools loaded" v={String(health?.tools ?? 0)} />
          <KV k="Plugins"      v={String(health?.plugins?.length ?? 0)} />
          <KV k="Agents"       v={(agents.length ? agents : health?.agents || []).join(", ") || "—"} />
          <div className="pt-1 text-[10px] text-jarvis-ice/40">
            Change these in <span className="text-jarvis-aqua">config.yaml</span> — requires backend restart.
          </div>
        </Section>

        <Section title="DATA">
          <ButtonRow label="Clear chat history" onClick={() => { if (confirm("Wipe chat?")) clearChat(); }} />
          <ButtonRow label="Clear media bay"    onClick={() => { if (confirm("Wipe media?")) clearMedia(); }} />
          <ButtonRow label="Clear tool history" onClick={() => { if (confirm("Wipe tool history?")) clearTools(); }} />
          <ButtonRow label="Clean slate (chat + media + tools + backend session)" danger onClick={cleanSlate} />
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="text-[9px] tracking-[0.35em] text-jarvis-cyan/70 uppercase">{title}</div>
      <div className="space-y-1.5 rounded-lg border border-jarvis-cyan/10 bg-jarvis-glass/40 p-3">
        {children}
      </div>
    </section>
  );
}

function Toggle({
  label, value, onChange,
}: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-3 cursor-pointer py-1">
      <span className="text-jarvis-ice/85">{label}</span>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className="relative w-9 h-5 rounded-full transition-colors"
        style={{
          background: value ? "rgba(125,211,252,0.7)" : "rgba(186,230,253,0.15)",
          boxShadow: value ? "0 0 12px rgba(125,211,252,0.6)" : "none",
        }}
      >
        <span
          className="absolute top-0.5 w-4 h-4 rounded-full bg-jarvis-ice transition-all"
          style={{ left: value ? 18 : 2 }}
        />
      </button>
    </label>
  );
}

function ButtonRow({
  label, onClick, danger = false,
}: { label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-2 py-1.5 rounded-md transition-colors border text-[11px] ${
        danger
          ? "border-jarvis-danger/30 text-jarvis-danger hover:bg-jarvis-danger/10 hover:border-jarvis-danger/55"
          : "border-jarvis-cyan/15 text-jarvis-ice/85 hover:bg-jarvis-cyan/10 hover:border-jarvis-cyan/40"
      }`}
    >
      {label}
    </button>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-0.5 text-[11px]">
      <span className="text-jarvis-ice/45">{k}</span>
      <span className="text-jarvis-ice/90 truncate max-w-[60%]" title={v}>{v}</span>
    </div>
  );
}
