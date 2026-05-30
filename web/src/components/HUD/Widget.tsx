/**
 * Widget — compact side-panel rendering of JARVIS.
 *
 * Shown when shellMode === "widget". Designed for the always-on-top, slim
 * Electron window that pops up beside the user's normal workflow. Surfaces
 * three things and nothing else:
 *
 *   1. Latest spoken / streaming reply (live)
 *   2. Latest media card (image, search, video, etc.) preview
 *   3. Mini command bar with voice toggle
 *
 * Designed to feel premium: frosted glass card, soft cyan accent, large
 * typography, no dense HUD chrome. Closes / shrinks via the chevron in
 * the header which IPCs back to "full" mode.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../../lib/store";
import { wsClient } from "../../lib/ws";
import { mic } from "../../lib/voice";
import { nextId } from "../../lib/store";

const jarvisIpc = (channel: string, payload?: unknown) => {
  try { (window as any).jarvis?.send?.(channel, payload); } catch { /* noop */ }
};

export default function Widget() {
  const chat = useStore((s) => s.chat);
  const media = useStore((s) => s.media);
  const micEnabled = useStore((s) => s.micEnabled);
  const micStatus = useStore((s) => s.micStatus);
  const pushChat = useStore((s) => s.pushChat);
  const setShellMode = useStore((s) => s.setShellMode);

  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const lastReply = useMemo(() => {
    for (let i = chat.length - 1; i >= 0; i--) {
      if (chat[i].role === "assistant") return chat[i];
    }
    return null;
  }, [chat]);

  const latestMedia = useMemo(() => {
    if (!media.length) return null;
    return media[media.length - 1];
  }, [media]);

  const latestItem = useMemo(() => {
    if (!latestMedia || !latestMedia.items?.length) return null;
    return latestMedia.items[latestMedia.items.length - 1];
  }, [latestMedia]);

  // Auto-focus on mount so the user can just start typing.
  useEffect(() => { inputRef.current?.focus(); }, []);

  const submit = () => {
    const text = draft.trim();
    if (!text) return;
    pushChat({ id: nextId(), role: "user", text, ts: Date.now() });
    wsClient.chat(text);
    setDraft("");
  };

  const toggleMic = async () => {
    if (micEnabled) {
      mic.stop();
    } else {
      await mic.start(
        (txt, isFinal) => {
          if (isFinal && txt.trim()) {
            pushChat({ id: nextId(), role: "user", text: txt.trim(), ts: Date.now() });
            wsClient.chat(txt.trim());
          } else {
            setDraft(txt);
          }
        },
        () => { jarvisIpc("jarvis:wake"); },
      );
    }
  };

  return (
    <div
      className="fixed inset-0 flex flex-col text-jarvis-ice"
      style={{
        background:
          "radial-gradient(120% 80% at 50% -10%, rgba(125,211,252,0.22), transparent 55%), " +
          "radial-gradient(120% 80% at 50% 110%, rgba(167,139,250,0.16), transparent 55%), " +
          "linear-gradient(180deg, #04080f 0%, #05101e 100%)",
      }}
    >
      {/* drag region — frameless windows on Win/macOS need an explicit
          -webkit-app-region: drag area for the user to move the window.
          Set as CSS inline because Tailwind has no built-in for it. */}
      <div
        className="h-9 flex items-center justify-between px-3 select-none border-b border-jarvis-cyan/10"
        style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
      >
        <div className="flex items-center gap-2 text-[10px] tracking-[0.45em] uppercase opacity-70">
          <span className="w-1.5 h-1.5 rounded-full bg-jarvis-cyan animate-pulse" />
          J · A · R · V · I · S
        </div>
        <div
          className="flex items-center gap-1"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
        >
          <button
            title="Expand to full HUD"
            onClick={() => {
              setShellMode("full");
              jarvisIpc("jarvis:set-widget-mode", false);
            }}
            className="w-7 h-7 rounded-md grid place-items-center text-jarvis-cyan/70 hover:text-jarvis-ice hover:bg-jarvis-cyan/10 transition"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M9 2H12V5M5 12H2V9M12 2L8 6M2 12L6 8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </button>
          <button
            title="Hide to tray"
            onClick={() => jarvisIpc("jarvis:hide")}
            className="w-7 h-7 rounded-md grid place-items-center text-jarvis-cyan/70 hover:text-jarvis-ice hover:bg-jarvis-cyan/10 transition"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M3 7H11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </div>

      {/* orb + status */}
      <div className="px-4 pt-4 pb-2 flex items-center gap-3">
        <MiniOrb />
        <div className="min-w-0">
          <div className="text-[10px] tracking-[0.35em] uppercase text-jarvis-cyan/60">
            {micEnabled ? micStatus || "listening" : "tap mic to wake"}
          </div>
          <div className="text-[13px] text-jarvis-ice/90 truncate">
            {lastReply ? lastReply.text.split(/[.!?\n]/)[0].slice(0, 60) || "standing by" : "standing by, sir."}
          </div>
        </div>
      </div>

      {/* primary card — latest media (image / search result / etc.) */}
      <div className="flex-1 px-4 pb-3 overflow-hidden">
        <div
          className="h-full rounded-2xl border border-jarvis-cyan/15 bg-jarvis-cyan/[0.03] backdrop-blur-md overflow-hidden flex flex-col"
          style={{
            boxShadow:
              "0 1px 0 0 rgba(255,255,255,0.06) inset, " +
              "0 0 32px -8px rgba(125,211,252,0.18), " +
              "0 18px 48px -20px rgba(8,16,30,0.8)",
          }}
        >
          {latestMedia && latestItem ? (
            <WidgetMediaCard kind={latestMedia.kind} item={latestItem} summary={latestMedia.summary} />
          ) : (
            <EmptyState />
          )}
        </div>
      </div>

      {/* mini command bar */}
      <div
        className="px-4 pb-4"
        style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
      >
        <div className="rounded-2xl border border-jarvis-cyan/20 bg-jarvis-ink-2/60 backdrop-blur-md p-2 flex items-end gap-2">
          <button
            title={micEnabled ? "stop mic" : "start mic"}
            onClick={toggleMic}
            className={
              "w-10 h-10 rounded-xl grid place-items-center transition border " +
              (micEnabled
                ? "bg-jarvis-cyan/20 border-jarvis-cyan/50 text-jarvis-ice"
                : "bg-transparent border-jarvis-cyan/20 text-jarvis-cyan/70 hover:bg-jarvis-cyan/10")
            }
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <rect x="6" y="2" width="4" height="8" rx="2" stroke="currentColor" strokeWidth="1.4" />
              <path d="M3.5 8a4.5 4.5 0 0 0 9 0M8 12.5V14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </button>
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={1}
            placeholder="Ask JARVIS…"
            className="flex-1 bg-transparent resize-none outline-none text-[14px] leading-snug py-2 text-jarvis-ice placeholder:text-jarvis-cyan/30"
          />
          <button
            onClick={submit}
            disabled={!draft.trim()}
            className="w-10 h-10 rounded-xl grid place-items-center bg-jarvis-cyan/20 border border-jarvis-cyan/40 text-jarvis-ice disabled:opacity-30 disabled:cursor-not-allowed hover:bg-jarvis-cyan/30 transition"
            title="send"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M2 7L12 7M7 2L12 7L7 12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

function MiniOrb() {
  const orbState = useStore((s) => s.orbState);
  const audio = useStore((s) => s.audioLevel);
  const ring = orbState === "listening"
    ? "stroke-jarvis-cyan"
    : orbState === "thinking"
      ? "stroke-jarvis-violet"
      : orbState === "speaking"
        ? "stroke-jarvis-aqua"
        : "stroke-jarvis-cyan/50";
  const scale = 1 + Math.min(0.3, audio * 1.2);
  return (
    <div className="w-12 h-12 shrink-0 relative">
      <div
        className="absolute inset-1 rounded-full bg-jarvis-cyan/15 blur-md transition-transform"
        style={{ transform: `scale(${scale})` }}
      />
      <svg viewBox="0 0 48 48" className="absolute inset-0 w-full h-full">
        <circle cx="24" cy="24" r="14" className={ring} strokeWidth="1.2" fill="none" />
        <circle cx="24" cy="24" r="9" className={ring} strokeWidth="0.8" fill="none" opacity="0.6" />
        <circle cx="24" cy="24" r="4" className="fill-jarvis-cyan/80" />
      </svg>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-2 text-center px-6">
      <div className="w-12 h-12 rounded-full border border-jarvis-cyan/25 grid place-items-center text-jarvis-cyan/60">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.3" />
          <path d="M10 6V10L13 12" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      </div>
      <div className="text-[11px] tracking-[0.3em] uppercase text-jarvis-cyan/55">Ready</div>
      <div className="text-[12px] text-jarvis-cyan/45 max-w-[80%]">
        Ask anything. Searches, images, and pages will surface here automatically.
      </div>
    </div>
  );
}

function WidgetMediaCard({
  kind,
  item,
  summary,
}: {
  kind: string;
  item: { url?: string; thumbnail?: string; title?: string; snippet?: string; source?: string };
  summary?: string;
}) {
  const isVisual = kind === "image" || kind === "video" || kind === "webcam" || kind === "model3d";
  const img = item.thumbnail || item.url;
  return (
    <div className="h-full flex flex-col">
      {isVisual && img && (
        <div className="w-full aspect-[5/4] bg-jarvis-ink-2/80 overflow-hidden border-b border-jarvis-cyan/10">
          {kind === "video" ? (
            <iframe
              src={item.url}
              title={item.title || "video"}
              className="w-full h-full"
              allow="autoplay; encrypted-media"
              allowFullScreen
            />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={img}
              alt={item.title || ""}
              className="w-full h-full object-cover"
              draggable={false}
            />
          )}
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-auto px-4 py-3 space-y-1.5">
        <div className="text-[9px] tracking-[0.4em] uppercase text-jarvis-cyan/55">
          {kind === "search" ? "Web result" :
           kind === "news"   ? "News" :
           kind === "image" ? "Image" :
           kind === "images" ? "Image search" :
           kind === "video" ? "Video" :
           kind === "page"  ? "Page"  :
           kind === "model3d" ? "3D model" :
           kind === "webcam" ? "Camera" :
           kind === "galaxy" ? "Memory" : kind}
        </div>
        <div className="text-[15px] font-medium text-jarvis-ice leading-snug">
          {item.title || summary || "(no title)"}
        </div>
        {item.snippet && (
          <div className="text-[12px] text-jarvis-cyan/70 leading-relaxed line-clamp-4">
            {item.snippet}
          </div>
        )}
        {item.source && (
          <div className="text-[10px] tracking-[0.25em] uppercase text-jarvis-cyan/40 pt-1.5">
            {item.source}
          </div>
        )}
      </div>
    </div>
  );
}
