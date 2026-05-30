/**
 * Live webcam feed with HUD overlay — corner brackets, recording dot,
 * face-tracking style guide rails, mirror toggle, snapshot, analyze.
 *
 * Default size is compact (aspect-video, capped at 240px tall) so the feed
 * never blows up the Media Bay. `large` mode opens up to 60vh for the
 * dedicated maximised card.
 */
import { useEffect, useRef, useState } from "react";
import { useStore, nextId, type MediaItem } from "../../lib/store";
import { wsClient } from "../../lib/ws";

export default function WebcamFeed({ item, large = false }: { item: MediaItem; large?: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [mirror, setMirror] = useState((item as any).mirror !== "0");
  const [err, setErr] = useState<string>("");
  const [now, setNow] = useState(new Date());
  const [flash, setFlash] = useState(false);
  const pushMedia = useStore((s) => s.pushMedia);
  const addAttachment = useStore((s) => s.addAttachment);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const s = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        });
        if (!mounted) { s.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = s;
        if (videoRef.current) {
          videoRef.current.srcObject = s;
          await videoRef.current.play();
        }
      } catch (e: any) {
        setErr(e?.message || "camera blocked");
      }
    })();
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => {
      mounted = false;
      clearInterval(id);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, []);

  // Capture current frame as JPEG data URL (smaller than PNG for LLM upload).
  const captureFrame = (): { dataUrl: string; w: number; h: number } | null => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return null;
    const c = document.createElement("canvas");
    // Cap output to 1024px on the long side — keeps payload reasonable.
    const MAX = 1024;
    const ratio = v.videoWidth / v.videoHeight;
    let w = v.videoWidth, h = v.videoHeight;
    if (w > MAX || h > MAX) {
      if (ratio >= 1) { w = MAX; h = Math.round(MAX / ratio); }
      else           { h = MAX; w = Math.round(MAX * ratio); }
    }
    c.width = w; c.height = h;
    const ctx = c.getContext("2d");
    if (!ctx) return null;
    if (mirror) { ctx.translate(c.width, 0); ctx.scale(-1, 1); }
    ctx.drawImage(v, 0, 0, c.width, c.height);
    return { dataUrl: c.toDataURL("image/jpeg", 0.85), w: c.width, h: c.height };
  };

  const doFlash = () => { setFlash(true); setTimeout(() => setFlash(false), 220); };

  // Snapshot: drop into Media Bay gallery only.
  const snapshot = () => {
    const f = captureFrame(); if (!f) return;
    doFlash();
    pushMedia({
      id: nextId(),
      kind: "image",
      items: [{ url: f.dataUrl, thumbnail: f.dataUrl,
                title: `snapshot ${new Date().toLocaleTimeString()}`,
                width: f.w, height: f.h }],
      summary: "Webcam snapshot",
      ts: Date.now(),
      expanded: null,
    });
  };

  // Analyze: snapshot, attach to chat, and ask JARVIS to describe what's there.
  const analyze = () => {
    const f = captureFrame(); if (!f) return;
    doFlash();
    addAttachment({
      type: "image",
      name: `webcam-${Date.now()}.jpg`,
      data_url: f.dataUrl,
      mime: "image/jpeg",
    });
    wsClient.chat("Analyze the attached webcam image — describe everything you see in detail.");
  };

  // Sizing: large = 60vh, compact = capped 240px tall.
  const sizeClasses = large
    ? "h-[60vh]"
    : "w-full aspect-video max-h-[240px] mx-auto";

  return (
    <div className="relative">
      <div className={`relative bg-black border border-jarvis-aqua/50 shadow-[0_0_20px_rgba(34,211,238,0.18)] ${sizeClasses}`}>
        {err ? (
          <div className="absolute inset-0 flex items-center justify-center text-mono text-xs text-jarvis-danger px-4 text-center">
            camera unavailable · {err}
          </div>
        ) : (
          <video
            ref={videoRef}
            autoPlay muted playsInline
            className={`absolute inset-0 w-full h-full object-cover ${mirror ? "[transform:scaleX(-1)]" : ""}`}
          />
        )}

        {/* Flash on capture */}
        <div
          className={`absolute inset-0 pointer-events-none bg-white transition-opacity ${flash ? "opacity-70" : "opacity-0"}`}
          style={{ transitionDuration: flash ? "40ms" : "220ms" }}
        />

        {/* Corner brackets */}
        <div className="absolute top-0 left-0 w-3 h-3 border-t-2 border-l-2 border-jarvis-aqua pointer-events-none" />
        <div className="absolute top-0 right-0 w-3 h-3 border-t-2 border-r-2 border-jarvis-aqua pointer-events-none" />
        <div className="absolute bottom-0 left-0 w-3 h-3 border-b-2 border-l-2 border-jarvis-aqua pointer-events-none" />
        <div className="absolute bottom-0 right-0 w-3 h-3 border-b-2 border-r-2 border-jarvis-aqua pointer-events-none" />

        {/* Crosshair guide rails */}
        <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 100 100" preserveAspectRatio="none">
          <line x1="50" y1="0"   x2="50" y2="5"   stroke="rgba(103,232,249,0.5)" strokeWidth="0.25" />
          <line x1="50" y1="95"  x2="50" y2="100" stroke="rgba(103,232,249,0.5)" strokeWidth="0.25" />
          <line x1="0"  y1="50"  x2="5"  y2="50"  stroke="rgba(103,232,249,0.5)" strokeWidth="0.25" />
          <line x1="95" y1="50"  x2="100" y2="50" stroke="rgba(103,232,249,0.5)" strokeWidth="0.25" />
          <rect x="38" y="28" width="24" height="44" fill="none" stroke="rgba(103,232,249,0.25)" strokeWidth="0.18" strokeDasharray="1 1" />
        </svg>

        {/* Top HUD strip */}
        <div className="absolute top-1.5 left-1.5 right-1.5 flex items-center justify-between text-mono text-[9px] text-jarvis-aqua pointer-events-none">
          <div className="flex items-center gap-1.5">
            <span className="w-1 h-1 bg-jarvis-danger rounded-full animate-pulse" />
            <span className="tracking-widest">REC · CAM-01</span>
          </div>
          <div className="tracking-widest bg-jarvis-ink/60 px-1 py-0.5 border border-jarvis-aqua/40">
            {now.toLocaleTimeString([], { hour12: false })}
          </div>
        </div>

        {/* Bottom HUD strip — controls */}
        <div className="absolute bottom-1.5 left-1.5 right-1.5 flex items-center justify-between gap-1 text-mono text-[9px]">
          <div className="flex gap-1 pointer-events-auto">
            <Pill onClick={() => setMirror((m) => !m)} active={mirror}>MIRROR</Pill>
            <Pill onClick={snapshot}>◉ SNAP</Pill>
            <Pill onClick={analyze} accent>◎ ANALYZE</Pill>
          </div>
          <div className="bg-jarvis-ink/60 px-1 py-0.5 border border-jarvis-aqua/40 text-jarvis-aqua tracking-widest">
            LIVE
          </div>
        </div>

        {/* Subtle scanline overlay */}
        <div
          className="absolute inset-0 pointer-events-none mix-blend-overlay opacity-25"
          style={{
            background: "repeating-linear-gradient(0deg, transparent 0, transparent 2px, rgba(34,211,238,0.10) 3px, transparent 4px)",
          }}
        />
      </div>
    </div>
  );
}

function Pill({ children, onClick, active = false, accent = false }: {
  children: React.ReactNode; onClick: () => void; active?: boolean; accent?: boolean;
}) {
  const cls = accent
    ? "border-jarvis-aqua/80 text-jarvis-aqua bg-jarvis-aqua/15 hover:bg-jarvis-aqua/25"
    : active
    ? "border-jarvis-aqua text-jarvis-aqua bg-jarvis-aqua/15"
    : "border-jarvis-cyan/40 text-jarvis-cyan/80 bg-jarvis-ink/60 hover:text-jarvis-aqua hover:border-jarvis-aqua/70";
  return (
    <button onClick={onClick} className={`px-1.5 py-0.5 border tracking-widest transition-colors ${cls}`}>
      {children}
    </button>
  );
}
