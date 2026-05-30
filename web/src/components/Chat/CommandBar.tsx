import { useEffect, useRef, useState } from "react";
import { useStore, nextId, type ChatAttachment } from "../../lib/store";
import { wsClient } from "../../lib/ws";
import { mic } from "../../lib/voice";
import ImageActions from "./ImageActions";

const MAX_IMAGE_BYTES = 8 * 1024 * 1024;

export default function CommandBar() {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pushChat = useStore((s) => s.pushChat);
  const micEnabled = useStore((s) => s.micEnabled);
  const micMode = useStore((s) => s.micMode);
  const wakeEnabled = useStore((s) => s.wakeEnabled);
  const setWakeEnabled = useStore((s) => s.setWakeEnabled);
  const micStatus = useStore((s) => s.micStatus);
  const voiceEnabled = useStore((s) => s.voiceEnabled);
  const setVoiceEnabled = useStore((s) => s.setVoiceEnabled);
  const voiceProfile = useStore((s) => s.voiceProfile);
  const connected = useStore((s) => s.connected);
  const pending = useStore((s) => s.pendingAttachments);
  const addAttachment = useStore((s) => s.addAttachment);
  const removeAttachment = useStore((s) => s.removeAttachment);
  const suggestions = useStore((s) => s.suggestions);

  const imageAttachments = pending.filter((a) => a.type === "image");
  const hasImages = imageAttachments.length > 0;

  // Auto-resize textarea height
  const resizeTextarea = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  };

  useEffect(() => {
    resizeTextarea();
  }, [value]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey && e.key === "/") || (e.key === "/" && document.activeElement?.tagName !== "TEXTAREA")) {
        e.preventDefault();
        textareaRef.current?.focus();
      }
      if (e.ctrlKey && e.key === "u") {
        e.preventDefault();
        fileInputRef.current?.click();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = () => {
    const v = value.trim();
    const st = useStore.getState();
    const hasAtt = st.pendingAttachments.length > 0;
    if (!v && !hasAtt) return;
    if (!v.startsWith("/")) {
      pushChat({
        id: nextId(),
        role: "user",
        text: v || (hasAtt ? "(attached)" : ""),
        ts: Date.now(),
        attachments: hasAtt ? [...st.pendingAttachments] : undefined,
      });
    }
    wsClient.chat(v);
    setValue("");
  };

  const sendSuggestion = (text: string) => {
    const t = text.trim();
    if (!t || !connected) return;
    pushChat({ id: nextId(), role: "user", text: t, ts: Date.now() });
    wsClient.chat(t);  // also clears the suggestion chips
    setValue("");
  };

  const toggleMic = async () => {
    if (micEnabled) {
      mic.stop();
      setWakeEnabled(false);
    } else {
      setWakeEnabled(true);
      await mic.start(
        (text, isFinal) => {
          if (isFinal && text.trim()) {
            const trimmed = text.trim();
            pushChat({ id: nextId(), role: "user", text: trimmed, ts: Date.now() });
            wsClient.chat(trimmed);
            setValue("");
          } else {
            setValue(text);
          }
        },
        (phrase) => {
          console.log("wake phrase:", phrase);
          // Bring the Electron window forward (or pop the widget) on wake.
          try { (window as any).jarvis?.send?.("jarvis:wake"); } catch { /* noop */ }
        }
      );
    }
  };

  const onFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    for (const f of files) await handleFile(f, addAttachment);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <div className="holo-panel h-full flex flex-col overflow-hidden">
      {/* ── Attached image previews ─────────────────────────────────── */}
      {pending.length > 0 && (
        <div className="flex flex-wrap gap-2 px-3 pt-2.5 pb-1 shrink-0">
          {pending.map((a, i) => (
            <div
              key={i}
              className="group relative flex items-center gap-2 pl-1 pr-2.5 py-1 rounded-xl border border-jarvis-aqua/35 bg-jarvis-aqua/8 hover:border-jarvis-aqua/60 hover:bg-jarvis-aqua/12 transition-all"
            >
              {a.type === "image" && (a.data_url || a.url) ? (
                <img
                  src={a.data_url || a.url}
                  alt=""
                  className="w-11 h-11 object-cover rounded-xl border border-jarvis-aqua/25 shrink-0"
                />
              ) : (
                <div className="w-11 h-11 rounded-xl border border-jarvis-aqua/20 bg-jarvis-cyan/5 flex items-center justify-center text-[9px] text-mono text-jarvis-cyan/60 shrink-0">
                  FILE
                </div>
              )}
              <span className="text-[10px] text-mono text-jarvis-aqua/80 truncate max-w-[100px]">
                {a.name}
              </span>
              <button
                onClick={() => removeAttachment(i)}
                className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-jarvis-ink border border-jarvis-danger/50 text-jarvis-danger flex items-center justify-center text-[9px] opacity-0 group-hover:opacity-100 transition-opacity"
                title="Remove"
              >×</button>
            </div>
          ))}
        </div>
      )}

      {/* ── Image action buttons ─────────────────────────────────────── */}
      {hasImages && (
        <div className="px-3 pb-1.5 shrink-0">
          <ImageActions images={imageAttachments} />
        </div>
      )}

      {/* ── Proactive suggestion chips ──────────────────────────────── */}
      {suggestions.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-3 pt-2 pb-0.5 shrink-0">
          {suggestions.map((s, i) => (
            <button
              key={i}
              onClick={() => sendSuggestion(s)}
              disabled={!connected}
              className="group flex items-center gap-1.5 pl-2 pr-2.5 py-1 rounded-full border border-jarvis-cyan/25 bg-jarvis-cyan/[0.06] hover:border-jarvis-cyan/60 hover:bg-jarvis-cyan/12 text-jarvis-ice/75 hover:text-jarvis-ice text-[11px] transition-all disabled:opacity-30"
              title="Send this"
            >
              <span className="text-jarvis-cyan/60 group-hover:text-jarvis-cyan text-[10px]">↳</span>
              {s}
            </button>
          ))}
        </div>
      )}

      {/* ── Input row ───────────────────────────────────────────────── */}
      <div className="flex items-end gap-2 px-2.5 py-2 shrink-0 mt-auto">
        {/* Mic */}
        <button
          onClick={toggleMic}
          title={micEnabled ? `mic ${micMode}` : "Start listening"}
          className={`w-9 h-9 flex items-center justify-center rounded-xl border transition-all shrink-0 ${
            !micEnabled
              ? "border-jarvis-cyan/15 text-jarvis-ice/60 hover:text-jarvis-ice hover:border-jarvis-cyan/45 hover:bg-jarvis-cyan/10"
              : micMode === "armed"
                ? "border-jarvis-aqua/70 text-jarvis-aqua bg-jarvis-aqua/15 animate-pulse_glow"
                : micMode === "speaking"
                  ? "border-jarvis-warn/70 text-jarvis-warn bg-jarvis-warn/10"
                  : "border-jarvis-cyan/60 text-jarvis-cyan bg-jarvis-cyan/10"
          }`}
        >
          <MicIcon active={micEnabled} />
        </button>

        {/* Speaker */}
        <button
          onClick={() => setVoiceEnabled(!voiceEnabled)}
          title={voiceEnabled ? `Mute JARVIS (${voiceProfile?.name ?? "…"})` : `Unmute JARVIS (${voiceProfile?.name ?? "…"})`}
          className={`w-9 h-9 flex items-center justify-center rounded-xl border transition-all shrink-0 ${
            voiceEnabled
              ? "border-jarvis-cyan/45 text-jarvis-cyan bg-jarvis-cyan/10"
              : "border-jarvis-cyan/15 text-jarvis-ice/40 hover:text-jarvis-ice/70 hover:border-jarvis-cyan/30"
          }`}
        >
          <SpeakerIcon muted={!voiceEnabled} />
        </button>

        {/* Upload */}
        <button
          onClick={() => fileInputRef.current?.click()}
          title="Attach image (Ctrl+U)"
          className={`w-9 h-9 flex items-center justify-center rounded-xl border transition-all shrink-0 ${
            hasImages
              ? "border-jarvis-aqua/60 text-jarvis-aqua bg-jarvis-aqua/10"
              : "border-jarvis-cyan/15 text-jarvis-ice/60 hover:text-jarvis-ice hover:border-jarvis-cyan/45 hover:bg-jarvis-cyan/10"
          }`}
        >
          <UploadIcon />
        </button>
        <input ref={fileInputRef} type="file" accept="image/*,*/*" multiple className="hidden" onChange={onFileSelect} />

        {/* Textarea */}
        <div className="flex-1 relative">
          <span className="absolute left-3 top-[9px] text-jarvis-cyan/50 text-mono select-none pointer-events-none">›</span>
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={connected ? "Speak to JARVIS, sir." : "Reconnecting…"}
            disabled={!connected}
            className="w-full bg-jarvis-glass border border-jarvis-cyan/15 focus:border-jarvis-cyan/55 outline-none pl-8 pr-10 py-[7px] rounded-xl text-jarvis-ice text-mono text-[13px] placeholder:text-jarvis-ice/30 backdrop-blur-md transition-all resize-none overflow-hidden leading-[1.45]"
          />
          <span className="absolute right-3 bottom-[9px] text-[10px] text-mono text-jarvis-ice/30 tabular-nums pointer-events-none">
            {value.length > 0 ? `${value.length}` : "↵"}
          </span>
        </div>

        {/* Send */}
        <button
          onClick={submit}
          disabled={(!value.trim() && pending.length === 0) || !connected}
          className="px-4 h-9 rounded-xl border border-jarvis-cyan/55 text-jarvis-ice bg-gradient-to-b from-jarvis-cyan/15 to-jarvis-cyan/5 hover:from-jarvis-cyan/25 hover:to-jarvis-cyan/10 hover:border-jarvis-cyan text-mono text-[11px] uppercase tracking-[0.25em] disabled:opacity-30 transition-all shadow-[0_0_24px_-8px_rgba(125,211,252,0.5)] shrink-0"
        >
          send
        </button>
      </div>

      {(wakeEnabled || micStatus) && (
        <div className="px-3 pb-1.5 text-[10px] text-mono text-jarvis-cyan/50 shrink-0">
          {micStatus ? `mic: ${micStatus}` : 'listening · say "Hey JARVIS" to wake'}
        </div>
      )}
    </div>
  );
}

// ── File handling ──────────────────────────────────────────────────────────

async function handleFile(f: File, add: (a: ChatAttachment) => void) {
  const isImage = f.type.startsWith("image/");
  if (isImage && f.size <= MAX_IMAGE_BYTES) {
    const dataUrl = await fileToDataURL(f);
    add({ type: "image", name: f.name, data_url: dataUrl, size: f.size, mime: f.type });
    return;
  }
  const form = new FormData();
  form.append("file", f);
  try {
    const resp = await fetch("/api/upload", { method: "POST", body: form });
    const data = await resp.json();
    if (data?.url) {
      add({ type: isImage ? "image" : "file", name: f.name, url: data.url, data_url: data.data_url || undefined, size: f.size, mime: f.type });
    }
  } catch (e) {
    console.error("upload failed", e);
  }
}

function fileToDataURL(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(f);
  });
}

// ── Icons ──────────────────────────────────────────────────────────────────

function MicIcon({ active }: { active: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="9" y="3" width="6" height="12" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8" />
      {active && <circle cx="12" cy="9" r="1.5" fill="currentColor" />}
    </svg>
  );
}

function SpeakerIcon({ muted }: { muted: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M11 5L6 9H3v6h3l5 4V5z" />
      {muted ? <path d="M16 9l5 5M21 9l-5 5" /> : <path d="M16 8a5 5 0 0 1 0 8M19 5a9 9 0 0 1 0 14" />}
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}
