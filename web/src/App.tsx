import { lazy, Suspense, useEffect, useRef, useState } from "react";
import Atmosphere from "./components/HUD/Atmosphere";
import BootSequence from "./components/Boot/BootSequence";
import ChatPanel from "./components/Chat/ChatPanel";
import CommandBar from "./components/Chat/CommandBar";
import DropZone from "./components/Chat/DropZone";
import TerminalPanel from "./components/HUD/TerminalPanel";
import CornerFrame from "./components/HUD/CornerFrame";
import DiagPanel from "./components/HUD/DiagPanel";
import Floating, { resetAllLayouts } from "./components/HUD/Floating";
import MissionLog from "./components/HUD/MissionLog";
import PlanPanel from "./components/HUD/PlanPanel";
import Reticle from "./components/HUD/Reticle";
import StatusBar from "./components/HUD/StatusBar";
import Settings from "./components/HUD/Settings";
import Subsystems from "./components/HUD/Subsystems";
import SwarmPanel from "./components/HUD/SwarmPanel";
import TopBar from "./components/HUD/TopBar";
import UptimePanel from "./components/HUD/UptimePanel";
import Widget from "./components/HUD/Widget";
import MediaHub from "./components/Media/MediaHub";
import Orb from "./components/Orb/Orb";
import ConfirmModal from "./components/Tools/ConfirmModal";
import ToolFeed from "./components/Tools/ToolFeed";

// Heavy components: split into separate chunks so they only load when needed.
// Saves ~30% of the initial JS payload (notably Three.js + react-three-fiber
// pull in via NeuralGalaxy/Model3DViewer, and the editor-grade prose CSS via
// ArticleReader).
const Lightbox      = lazy(() => import("./components/Media/Lightbox"));
const ArticleReader = lazy(() => import("./components/Media/ArticleReader"));
import { getHealth } from "./lib/api";
import { useStore, nextId, type MediaKind } from "./lib/store";
import { refreshVoiceProfile, streamSpeak } from "./lib/voice";
import { wsClient } from "./lib/ws";

const GREETING_SESSION_KEY = "jarvis.greeting.sent.v1";

/**
 * Default panel positions. Recomputed at first load for current viewport.
 * Stored sizes/positions persist in localStorage thereafter.
 */
function defaults() {
  const W = window.innerWidth;
  const H = window.innerHeight;
  const M = 16;
  const TOP = 76;
  const BOTTOM = 48;
  const colL = 320;
  const colR = 380;
  const halfH = (H - TOP - BOTTOM - 8) / 2;
  return {
    diag:      { x: M, y: TOP, w: colL, h: 260 },
    subs:      { x: M, y: TOP + 268, w: colL, h: 360 },
    terminal:  { x: M, y: TOP + 268 + 368, w: colL, h: Math.max(180, H - TOP - 268 - 368 - BOTTOM) },
    uptime:    { x: M + colL + 12, y: TOP, w: 220, h: 136 },
    chat:      { x: W - colR - M, y: TOP, w: colR, h: halfH * 2 - 200 },
    mission:   { x: W - colR - M, y: H - BOTTOM - 200 - 8 - 110, w: colR, h: 110 },
    toolFeed:  { x: W - colR - M, y: H - BOTTOM - 200, w: colR, h: 200 },

    // Media hubs — each kind in its own panel. Initial positions cascade
    // diagonally so they don't all stack at one spot; user can drag.
    swarm:       { x: 340,  y: 80,  w: 360, h: 320 },
    plan:        { x: 340,  y: 80,  w: 360, h: 300 },
    settings:    { x: 380,  y: 120, w: 420, h: 540 },
    reader:      { x: 480,  y: 140, w: 720, h: 640 },
    images:      { x: 380,  y: 120, w: 640, h: 480 },
    videos:      { x: 420,  y: 160, w: 680, h: 460 },
    websearch:   { x: 460,  y: 200, w: 560, h: 480 },
    imagesearch: { x: 500,  y: 240, w: 600, h: 500 },
    news:        { x: 540,  y: 280, w: 580, h: 520 },
    pages:       { x: 580,  y: 320, w: 720, h: 520 },
    webcam:      { x: 620,  y: 360, w: 520, h: 420 },
    memory:      { x: 660,  y: 400, w: 600, h: 520 },
    model3d:     { x: 700,  y: 200, w: 560, h: 520 },

    cmd:       { x: (W - 760) / 2, y: H - BOTTOM - 100, w: 760, h: 72 },
  };
}

function useViewport() {
  const [viewport, setViewport] = useState(() => ({
    w: typeof window !== "undefined" ? window.innerWidth : 1200,
    h: typeof window !== "undefined" ? window.innerHeight : 800,
  }));

  useEffect(() => {
    let raf = 0;
    const update = () => {
      raf = 0;
      setViewport({ w: window.innerWidth, h: window.innerHeight });
    };
    const onResize = () => {
      if (raf) return;
      raf = window.requestAnimationFrame(update);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, []);

  return viewport;
}

export default function App() {
  const setHealth = useStore((s) => s.setHealth);
  const media = useStore((s) => s.media);
  const shellMode = useStore((s) => s.shellMode);
  const setShellMode = useStore((s) => s.setShellMode);
  const viewport = useViewport();
  const hiddenRef = useRef(false);
  const lastMediaLenRef = useRef(0);

  useEffect(() => {
    wsClient.connect();
    refreshVoiceProfile();
    getHealth().then(setHealth).catch(() => undefined);
    const id = setInterval(() => {
      getHealth().then(setHealth).catch(() => undefined);
    }, 15_000);
    return () => clearInterval(id);
  }, [setHealth]);

  // ── Electron integration: track shell mode + window visibility ──────────
  useEffect(() => {
    const j = (window as any).jarvis;
    if (!j) return; // running in a plain browser — skip

    // Sync the renderer's shellMode with whatever the main process reports.
    j.invoke("jarvis:request-mode").then((mode: string | null) => {
      if (mode === "widget" || mode === "full") setShellMode(mode);
    }).catch(() => undefined);

    const offMode = j.on("jarvis:mode-changed", (mode: string) => {
      if (mode === "widget" || mode === "full") setShellMode(mode);
    });
    const offVis = j.on("jarvis:visibility-changed", (visible: boolean) => {
      hiddenRef.current = !visible;
    });
    return () => { offMode?.(); offVis?.(); };
  }, [setShellMode]);

  // ── Auto-popup widget when new media arrives while the window is hidden.
  useEffect(() => {
    const prev = lastMediaLenRef.current;
    const total = media.reduce((n, m) => n + (m.items?.length || 0), 0);
    if (total > prev && hiddenRef.current) {
      const j = (window as any).jarvis;
      if (j) j.send("jarvis:set-widget-mode", true);
    }
    lastMediaLenRef.current = total;
  }, [media]);

  useEffect(() => {
    let lastLen = 0;
    let lastId = "";
    return useStore.subscribe((state) => {
      const last = state.chat[state.chat.length - 1];
      if (!last || last.role !== "assistant") return;
      if (last.id !== lastId) {
        lastId = last.id;
        lastLen = 0;
      }
      const grew = last.text.length !== lastLen;
      lastLen = last.text.length;
      if (grew || !last.streaming) {
        console.log("[App:TTS] streamSpeak id=%s len=%d grew=%s isFinal=%s streaming=%s", last.id, last.text.length, grew, !last.streaming, last.streaming);
        streamSpeak(last.id, last.text, !last.streaming);
      }
    });
  }, []);

  // ── One-shot, time-aware greeting once the boot sequence clears.
  // Pushed as an assistant chat entry so the TTS subscribe above speaks it
  // automatically (honours the voice-enabled toggle; no double-speak).
  const pushChat = useStore((s) => s.pushChat);
  const booted = useStore((s) => s.booted);
  const greetedRef = useRef(false);
  useEffect(() => {
    if (!booted || greetedRef.current) return;
    greetedRef.current = true;
    const h = new Date().getHours();
    const part = h < 12 ? "morning" : h < 18 ? "afternoon" : "evening";
    const text = `Good ${part}, sir. All systems are online and at your service.`;
    try {
      if (sessionStorage.getItem(GREETING_SESSION_KEY) === "1") return;
      sessionStorage.setItem(GREETING_SESSION_KEY, "1");
    } catch { /* noop */ }
    // Small beat so it lands after the boot overlay finishes fading out.
    const t = setTimeout(() => {
      pushChat({ id: nextId(), role: "assistant", text, ts: Date.now() });
    }, 600);
    return () => clearTimeout(t);
  }, [booted, pushChat]);

  const D = defaults();
  const swarms = useStore((s) => s.swarms);
  const hasSwarms = swarms.length > 0;
  const hasPlan = useStore((s) => s.plan != null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Helper: which hubs have at least 1 item?
  const has = (kinds: MediaKind[]) => media.some((m) => kinds.includes(m.kind));

  // ── Widget mode — slim side panel, replaces the full HUD entirely.
  if (shellMode === "widget") {
    return (
      <div className="relative w-screen h-screen overflow-hidden">
        <Atmosphere />
        <Widget />
        <ConfirmModal />
        <BootSequence />
      </div>
    );
  }

  if (viewport.w < 900) {
    return (
      <div className="relative w-screen h-screen overflow-hidden">
        <Atmosphere />
        <Orb />
        <CornerFrame />
        <TopBar />
        <StatusBar />

        <div className="fixed left-4 right-4 top-[76px] z-20 grid h-[136px] grid-cols-[minmax(0,1fr)_minmax(168px,190px)] gap-3 pointer-events-auto">
          <div className="min-w-0 overflow-hidden">
            <DiagPanel />
          </div>
          <UptimePanel />
        </div>

        <div className="fixed left-4 right-4 top-[224px] bottom-[136px] z-20 min-h-[260px] pointer-events-auto">
          <ChatPanel />
        </div>

        <div className="fixed left-4 right-4 bottom-16 z-30 h-[72px] pointer-events-auto">
          <CommandBar />
        </div>

        <Reticle />
        <Suspense fallback={null}>
          <Lightbox />
          <ArticleReader />
        </Suspense>
        <ConfirmModal />
        <DropZone />
        <BootSequence />
      </div>
    );
  }

  return (
    <div className="relative w-screen h-screen overflow-hidden">
      <Atmosphere />
      <Orb />

      {/* Fixed HUD chrome — not draggable */}
      <CornerFrame />
      <TopBar />
      <StatusBar />

      {/* Reset-layout button (lower right corner near StatusBar) */}
      <button
        onClick={() => {
          if (confirm("Reset all panel positions and sizes?")) resetAllLayouts();
        }}
        title="Reset layout"
        className="fixed bottom-12 right-4 z-50 glass-chip hover:bg-jarvis-cyan/10 hover:text-jarvis-ice transition-colors"
      >
        ⟲ layout
      </button>

      {/* Settings toggle */}
      <button
        onClick={() => setSettingsOpen((v) => !v)}
        title="Settings"
        className="fixed bottom-12 right-[200px] z-50 glass-chip hover:bg-jarvis-cyan/10 hover:text-jarvis-ice transition-colors"
      >
        ⚙ settings
      </button>

      {/* Collapse-to-widget button — slides into the side panel mode */}
      <button
        onClick={() => {
          setShellMode("widget");
          try { (window as any).jarvis?.send?.("jarvis:set-widget-mode", true); } catch { /* noop */ }
        }}
        title="Collapse to widget (Ctrl+Shift+J)"
        className="fixed bottom-12 right-28 z-50 glass-chip hover:bg-jarvis-cyan/10 hover:text-jarvis-ice transition-colors"
      >
        ◱ widget
      </button>

      {/* Floating, movable + resizable panels */}
      <Floating id="diag"     defaultBox={D.diag}     minW={260} minH={180}><DiagPanel /></Floating>
      <Floating id="uptime"   defaultBox={D.uptime}   minW={180} minH={118}><UptimePanel /></Floating>
      <Floating id="subs"     defaultBox={D.subs}     minW={260} minH={220}><Subsystems /></Floating>
      <Floating id="terminal" defaultBox={D.terminal} minW={260} minH={180}><TerminalPanel /></Floating>

      <Floating id="chat"     defaultBox={D.chat}     minW={300} minH={260}><ChatPanel /></Floating>
      <Floating id="mission"  defaultBox={D.mission}  minW={280} minH={90}><MissionLog /></Floating>
      <Floating id="toolFeed" defaultBox={D.toolFeed} minW={280} minH={140}><ToolFeed /></Floating>
      {hasSwarms && (
        <Floating id="swarm" defaultBox={D.swarm} minW={300} minH={200} z={23}>
          <SwarmPanel />
        </Floating>
      )}
      {hasPlan && (
        <Floating id="plan" defaultBox={D.plan} minW={300} minH={180} z={24}>
          <PlanPanel />
        </Floating>
      )}
      {settingsOpen && (
        <Floating id="settings" defaultBox={D.settings} minW={340} minH={300} z={28}>
          <Settings />
        </Floating>
      )}
      {/* Pinned reader — when readerPinned=true the ArticleReader component
          renders only the inner article surface, so we wrap it in a
          Floating panel here. Modal mode (unpinned) is mounted directly
          below as fullscreen overlay. */}
      <PinnedReader defaultBox={D.reader} />

      {/* ── Per-kind media hubs. Each only renders when has items. ── */}
      {has(["image"]) && (
        <Floating id="hub.images" defaultBox={D.images} minW={360} minH={260} z={22}>
          <MediaHub kinds={["image"]} title="IMAGE GEN" accent="#a5f3fc" />
        </Floating>
      )}
      {has(["video", "videos"]) && (
        <Floating id="hub.videos" defaultBox={D.videos} minW={360} minH={280} z={22}>
          <MediaHub kinds={["video", "videos"]} title="VIDEOS" accent="#fbbf24" />
        </Floating>
      )}
      {has(["search"]) && (
        <Floating id="hub.websearch" defaultBox={D.websearch} minW={340} minH={260} z={22}>
          <MediaHub kinds={["search"]} title="WEB SEARCH" accent="#7dd3fc" />
        </Floating>
      )}
      {has(["news"]) && (
        <Floating id="hub.news" defaultBox={D.news} minW={340} minH={260} z={22}>
          <MediaHub kinds={["news"]} title="NEWS" accent="#fca5a5" />
        </Floating>
      )}
      {has(["images"]) && (
        <Floating id="hub.imagesearch" defaultBox={D.imagesearch} minW={360} minH={280} z={22}>
          <MediaHub kinds={["images"]} title="IMAGE SEARCH" accent="#7dd3fc" />
        </Floating>
      )}
      {has(["page", "pdf"]) && (
        <Floating id="hub.pages" defaultBox={D.pages} minW={400} minH={320} z={22}>
          <MediaHub kinds={["page", "pdf"]} title="PAGES" accent="#bae6fd" />
        </Floating>
      )}
      {has(["webcam"]) && (
        <Floating id="hub.webcam" defaultBox={D.webcam} minW={340} minH={260} z={22}>
          <MediaHub kinds={["webcam"]} title="CAMERA" accent="#fb7185" />
        </Floating>
      )}
      {has(["galaxy"]) && (
        <Floating id="hub.memory" defaultBox={D.memory} minW={380} minH={320} z={22}>
          <MediaHub kinds={["galaxy"]} title="MEMORY" accent="#a78bfa" />
        </Floating>
      )}
      {has(["model3d"]) && (
        <Floating id="hub.model3d" defaultBox={D.model3d} minW={360} minH={320} z={22}>
          <MediaHub kinds={["model3d"]} title="3D MODELS" accent="#bae6fd" />
        </Floating>
      )}

      {/* Command bar — height auto-grows when images attached (so 3D/img2img/analyze visible) */}
      <Floating id="cmd" defaultBox={D.cmd} minW={420} minH={72} autoHeight>
        <CommandBar />
      </Floating>

      <Reticle />
      <Suspense fallback={null}>
        <Lightbox />
        <ArticleReader />
      </Suspense>
      <ConfirmModal />
      <DropZone />
      <BootSequence />
    </div>
  );
}

/**
 * When the user pins the article reader, render it inside a Floating panel.
 * Otherwise the modal-mode ArticleReader handles its own portal.
 */
function PinnedReader({ defaultBox }: { defaultBox: { x: number; y: number; w: number; h: number } }) {
  const url = useStore((s) => s.reader);
  const pinned = useStore((s) => s.readerPinned);
  if (!url || !pinned) return null;
  return (
    <Floating id="reader.pinned" defaultBox={defaultBox} minW={420} minH={320} z={29}>
      <Suspense fallback={null}>
        <ArticleReader />
      </Suspense>
    </Floating>
  );
}
