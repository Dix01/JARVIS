/**
 * Fullscreen lightbox — image / page preview without leaving JARVIS.
 */
import { useEffect } from "react";
import { useStore } from "../../lib/store";

export default function Lightbox() {
  const lb = useStore((s) => s.lightbox);
  const set = useStore((s) => s.setLightbox);
  const pushMedia = useStore((s) => s.pushMedia);

  useEffect(() => {
    if (!lb) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") set(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lb, set]);

  if (!lb) return null;
  const { kind, item } = lb;

  return (
    <div
      className="fixed inset-0 z-[200] bg-black/80 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={() => set(null)}
    >
      <div
        className="relative max-w-[92vw] max-h-[92vh] holo-frame bg-black/40"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-jarvis-cyan/30 bg-jarvis-cyan/5">
          <div className="min-w-0">
            <div className="text-mono text-[12px] text-jarvis-aqua truncate">{item.title || item.url}</div>
            <div className="text-mono text-[10px] text-jarvis-cyan/50 truncate">{item.source || item.url}</div>
          </div>
          <div className="flex gap-1 shrink-0">
            {kind !== "image" && (
              <button
                onClick={() => {
                  // promote into Media Bay as a persistent iframe
                  pushMedia({
                    id: `lb-${Date.now()}`, kind: "page",
                    items: [item], summary: item.title || item.url,
                    ts: Date.now(), expanded: 0,
                  });
                  set(null);
                }}
                className="text-mono text-[10px] text-jarvis-cyan border border-jarvis-cyan/40 px-2 py-0.5 hover:bg-jarvis-cyan/10"
              >
                pin to bay
              </button>
            )}
            <button
              onClick={() => set(null)}
              className="text-mono text-[10px] text-jarvis-cyan border border-jarvis-cyan/40 px-2 py-0.5 hover:bg-jarvis-cyan/10"
            >
              close · esc
            </button>
          </div>
        </div>

        {kind === "image" ? (
          <img
            src={item.url}
            alt={item.title || ""}
            referrerPolicy="no-referrer"
            className="max-h-[82vh] max-w-[88vw] object-contain bg-black"
          />
        ) : (
          <iframe
            src={`/api/proxy?url=${encodeURIComponent(item.url)}`}
            title={item.title || item.url}
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation"
            referrerPolicy="no-referrer"
            className="w-[88vw] h-[82vh] bg-white"
          />
        )}
      </div>
    </div>
  );
}
