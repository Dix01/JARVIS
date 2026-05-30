/**
 * 3D model viewer - wraps Google's `<model-viewer>` web component for inline
 * GLB preview with orbit / zoom / AR-ready embed.
 */
import { useEffect, useState } from "react";
import type { MediaItem } from "../../lib/store";

let scriptInjected = false;
function ensureModelViewerScript(): void {
  if (scriptInjected || typeof document === "undefined") return;
  scriptInjected = true;
  const s = document.createElement("script");
  s.type = "module";
  s.src = "https://ajax.googleapis.com/ajax/libs/model-viewer/4.0.0/model-viewer.min.js";
  document.head.appendChild(s);
}

export default function Model3DViewer({ item, large = false }: { item: MediaItem; large?: boolean }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    ensureModelViewerScript();
    const id = setInterval(() => {
      if (customElements.get("model-viewer")) {
        setReady(true);
        clearInterval(id);
      }
    }, 80);
    return () => clearInterval(id);
  }, []);

  if (!item?.url) return null;
  const height = large ? "h-[80vh] min-h-[560px]" : "h-[52vh] min-h-[360px]";

  return (
    <div className={`relative w-full ${height} overflow-visible`}>
      <div className="absolute inset-x-[7%] bottom-[7%] h-px bg-gradient-to-r from-transparent via-jarvis-aqua/30 to-transparent pointer-events-none" />
      <div className="absolute inset-0 drop-shadow-[0_26px_45px_rgba(0,0,0,0.42)]">
        {ready ? (
          // @ts-ignore - custom element
          <model-viewer
            src={item.url}
            alt={item.title || "3D model"}
            camera-controls
            camera-orbit="0deg 70deg auto"
            field-of-view="28deg"
            min-camera-orbit="auto auto 80%"
            max-camera-orbit="auto auto 240%"
            shadow-intensity="0.35"
            shadow-softness="0.85"
            exposure="1.12"
            environment-image="neutral"
            interaction-prompt="auto"
            auto-rotate
            auto-rotate-delay="1200"
            rotation-per-second="24deg"
            ar
            ar-modes="webxr scene-viewer quick-look"
            style={{ width: "100%", height: "100%", background: "transparent" }}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-mono text-[11px] text-jarvis-cyan/60 tracking-widest">
            BOOTING 3D VIEWER...
          </div>
        )}
      </div>

      <div className="absolute bottom-3 right-2 flex items-center gap-2 text-mono text-[10px] pointer-events-none">
        <a
          href={item.url}
          download
          className="pointer-events-auto rounded-full border border-jarvis-aqua/25 bg-jarvis-ink/45 px-2.5 py-1 tracking-widest text-jarvis-cyan/75 backdrop-blur-md transition-colors hover:border-jarvis-aqua/60 hover:text-jarvis-aqua"
          aria-label="Download GLB model"
        >
          GLB
        </a>
      </div>
    </div>
  );
}
