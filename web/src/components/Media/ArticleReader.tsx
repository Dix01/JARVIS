/**
 * ARTICLE READER — themed in-app news reader.
 *
 * Fetches /api/reader?url=... which server-side resolves Google News
 * wrappers, follows redirects, and extracts clean article content via
 * trafilatura. The returned content_html is rendered inside a styled
 * scrollable overlay matching the JARVIS theme — no external browser,
 * no broken iframes.
 */
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { useStore } from "../../lib/store";

interface Article {
  ok: boolean;
  url: string;
  title: string;
  author: string;
  published: string;
  site: string;
  image: string;
  description: string;
  content_html: string;
  error?: string;
}

export default function ArticleReader() {
  const url = useStore((s) => s.reader);
  const pinned = useStore((s) => s.readerPinned);
  const setPinned = useStore((s) => s.setReaderPinned);
  const close = () => useStore.getState().setReader(null);

  const [data, setData] = useState<Article | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!url) {
      setData(null); setLoading(false); setErr(null);
      return;
    }
    setLoading(true);
    setErr(null);
    setData(null);
    const ctrl = new AbortController();
    fetch(`/api/reader?url=${encodeURIComponent(url)}`, { signal: ctrl.signal })
      .then(async (r) => {
        const j = (await r.json()) as Article;
        if (!j.ok) throw new Error(j.error || "reader failed");
        setData(j);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setErr(String(e.message || e));
      })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [url]);

  useEffect(() => {
    if (!url) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [url]);

  // When pinned, the reader is rendered by App.tsx inside its own Floating
  // panel, so this component renders only the inner article surface (no
  // backdrop, no animated modal scale). When unpinned, the full-screen
  // modal overlay is used.
  const inner = (
    <div className="holo-panel relative flex flex-col overflow-hidden h-full w-full">
            {/* Header bar */}
            <div className="panel-header flex items-center justify-between gap-3 px-4 py-2.5 shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className="text-mono text-[9.5px] tracking-[0.2em] uppercase px-1.5 py-0.5 rounded"
                  style={{
                    background: "rgba(252,165,165,0.12)",
                    border: "1px solid rgba(252,165,165,0.4)",
                    color: "#fca5a5",
                  }}
                >
                  {data?.site || "NEWS"}
                </span>
                {data?.published && (
                  <span className="text-mono text-[10px] text-jarvis-ice/45">{data.published}</span>
                )}
                {data?.author && (
                  <span className="text-mono text-[10px] text-jarvis-ice/55 truncate">· {data.author}</span>
                )}
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <a
                  href={data?.url || url || "#"}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="glass-chip hover:bg-jarvis-cyan/10 hover:text-jarvis-ice transition-colors"
                  title="Open original article"
                >
                  open ↗
                </a>
                <button
                  onClick={() => setPinned(!pinned)}
                  className="glass-chip hover:bg-jarvis-cyan/10 hover:text-jarvis-ice transition-colors"
                  title={pinned ? "Float back to modal" : "Pin as draggable panel"}
                >
                  {pinned ? "unpin" : "pin"}
                </button>
                <button
                  onClick={close}
                  className="glass-chip hover:bg-jarvis-cyan/10 hover:text-jarvis-ice transition-colors"
                >
                  close{pinned ? "" : " · esc"}
                </button>
              </div>
            </div>

            {/* Body */}
            <div className="flex-1 min-h-0 overflow-y-auto px-7 py-6 scroll-smooth">
              {loading && (
                <div className="flex flex-col items-center justify-center h-full gap-3 text-mono text-[11px] text-jarvis-cyan/70">
                  <motion.div
                    className="w-8 h-8 rounded-full border-2 border-jarvis-cyan/30 border-t-jarvis-cyan"
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                  />
                  <span className="tracking-[0.3em] uppercase">decrypting article…</span>
                </div>
              )}
              {err && !loading && (
                <div className="flex flex-col items-center gap-4 text-center py-12">
                  <div className="text-mono text-[11px] tracking-[0.25em] uppercase text-jarvis-danger">
                    Reader error
                  </div>
                  <div className="text-[12px] text-jarvis-ice/65 max-w-md break-words">{err}</div>
                  {url && (
                    <a
                      href={url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="glass-chip hover:bg-jarvis-cyan/10 hover:text-jarvis-ice transition-colors"
                    >
                      open original in browser ↗
                    </a>
                  )}
                </div>
              )}
              {data && !data.content_html.trim() && !loading && !err && (
                <div className="flex flex-col items-center gap-4 text-center py-12">
                  <div className="text-mono text-[11px] tracking-[0.25em] uppercase text-jarvis-ice/55">
                    No readable content extracted
                  </div>
                  <div className="text-[12px] text-jarvis-ice/55 max-w-md">
                    Publisher blocked the in-app reader. Open externally:
                  </div>
                  <a
                    href={data.url || url || "#"}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="glass-chip hover:bg-jarvis-cyan/10 hover:text-jarvis-ice transition-colors"
                  >
                    open original ↗
                  </a>
                </div>
              )}
              {data && data.content_html.trim() && !loading && !err && (
                <article>
                  {data.image && (
                    <img
                      src={data.image}
                      alt=""
                      referrerPolicy="no-referrer"
                      className="w-full max-h-[360px] object-cover rounded-xl mb-5"
                      style={{ border: "1px solid rgba(186,230,253,0.18)" }}
                      onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                    />
                  )}
                  <h1
                    className="text-jarvis-ice font-display font-medium leading-[1.15] mb-3"
                    style={{ fontSize: "clamp(22px, 2.4vw, 32px)" }}
                  >
                    {data.title}
                  </h1>
                  {data.description && (
                    <p className="text-[15px] text-jarvis-ice/70 italic leading-relaxed mb-6 border-l-2 border-jarvis-cyan/30 pl-4">
                      {data.description}
                    </p>
                  )}
                  <div
                    className="reader-body text-[15.5px] text-jarvis-ice/90 leading-[1.7]"
                    dangerouslySetInnerHTML={{ __html: data.content_html }}
                  />
                </article>
              )}
            </div>
    </div>
  );

  if (!url) return null;

  if (pinned) {
    // Rendered by App.tsx inside a Floating panel; just return inner.
    return inner;
  }

  return (
    <AnimatePresence>
      <motion.div
        key="reader-modal"
        className="fixed inset-0 z-[200] flex items-center justify-center p-6"
        style={{ background: "rgba(3,7,15,0.82)", backdropFilter: "blur(20px) saturate(140%)" }}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={close}
      >
        <motion.div
          style={{ width: "min(880px, 94vw)", height: "min(88vh, 1100px)" }}
          initial={{ scale: 0.94, y: 22, opacity: 0 }}
          animate={{ scale: 1, y: 0, opacity: 1 }}
          exit={{ scale: 0.94, y: 22, opacity: 0 }}
          transition={{ duration: 0.36, ease: [0.16, 1, 0.3, 1] }}
          onClick={(e) => e.stopPropagation()}
        >
          {inner}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
