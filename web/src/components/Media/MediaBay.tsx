/**
 * MEDIA BAY — v4 "Liquid Gallery".
 *
 * Premium glass dock. Sits BELOW the orb (never overlaps). Modern card
 * grid w/ rounded surfaces, soft gradient overlays, frictionless hover lift.
 * Old CRT scanlines + harsh cyan brackets replaced w/ subtle shimmer +
 * gradient halos. Same store API as v3.
 */
import { AnimatePresence, motion } from "framer-motion";
import { useMemo, useState } from "react";
import { nextId, useStore, type MediaCard, type MediaItem, type MediaKind } from "../../lib/store";
import { wsClient } from "../../lib/ws";
import MediaReveal from "./MediaReveal";
import Model3DViewer from "./Model3DViewer";
import NeuralGalaxy from "./NeuralGalaxy";
import WebcamFeed from "./WebcamFeed";

type FilterKey = "all" | "search" | "image" | "video" | "page" | "webcam" | "galaxy" | "model3d";

const FILTERS: { key: FilterKey; label: string; match: MediaKind[] }[] = [
  { key: "all",     label: "ALL",    match: ["search","image","images","video","videos","page","pdf","webcam","galaxy","model3d"] },
  { key: "search",  label: "WEB",    match: ["search"] },
  { key: "image",   label: "IMAGES", match: ["image","images"] },
  { key: "video",   label: "VIDEOS", match: ["video","videos"] },
  { key: "page",    label: "PAGES",  match: ["page","pdf"] },
  { key: "webcam",  label: "CAM",    match: ["webcam"] },
  { key: "galaxy",  label: "MEMORY", match: ["galaxy"] },
  { key: "model3d", label: "3D",     match: ["model3d"] },
];

export default function MediaBay() {
  const media       = useStore((s) => s.media);
  const setLightbox = useStore((s) => s.setLightbox);
  const removeMedia = useStore((s) => s.removeMedia);
  const pinMedia    = useStore((s) => s.pinMedia);
  const expandMedia = useStore((s) => s.expandMedia);
  const pushMedia   = useStore((s) => s.pushMedia);

  const [filter, setFilter] = useState<FilterKey>("all");
  const [collapsed, setCollapsed] = useState(false);
  const [maximized, setMaximized] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);

  const counts = useMemo(() => {
    const c: Record<FilterKey, number> = { all: 0, search: 0, image: 0, video: 0, page: 0, webcam: 0, galaxy: 0, model3d: 0 };
    for (const m of media) {
      c.all++;
      for (const f of FILTERS) {
        if (f.key !== "all" && f.match.includes(m.kind)) c[f.key]++;
      }
    }
    return c;
  }, [media]);

  const filtered = useMemo(() => {
    const allowed = FILTERS.find((f) => f.key === filter)!.match;
    const list = media.filter((m) => allowed.includes(m.kind));
    return [...list].sort((a, b) => {
      if (!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1;
      return b.ts - a.ts;
    });
  }, [media, filter]);

  if (media.length === 0) return null;
  const maxCard = maximized ? media.find((m) => m.id === maximized) : null;
  const maxIsModel3D = maxCard?.kind === "model3d";

  const openWebcam = () => {
    pushMedia({
      id: nextId(),
      kind: "webcam",
      items: [{ url: "webcam://local", title: "WEBCAM FEED", thumbnail: "" }],
      summary: "Webcam opened (manual)",
      ts: Date.now(),
      expanded: null,
      pinned: true,
    });
  };

  const openGalaxy = () => {
    wsClient.chat("show my memory galaxy");
  };

  return (
    <>
      <motion.div
        layout
        className={`holo-panel relative flex flex-col overflow-hidden h-full ${collapsed ? "!h-11" : ""}`}
      >
        {/* ── Header ─────────────────────────────────────────────── */}
        <div className="panel-header relative shrink-0">
          <div className="flex items-center justify-between gap-3 px-4 py-2.5">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="relative">
                <div className="w-1.5 h-1.5 bg-jarvis-aqua rounded-full animate-pulse_glow shrink-0" />
                <div className="absolute inset-0 w-1.5 h-1.5 bg-jarvis-aqua blur-md opacity-70" />
              </div>
              <span className="text-display text-[11px] tracking-[0.4em] text-shimmer font-medium">MEDIA&nbsp;BAY</span>
              <span className="glass-chip">{media.length}</span>
            </div>

            {!collapsed && (
              <div className="flex items-center gap-1 overflow-x-auto no-scrollbar flex-1 justify-center">
                {FILTERS.map((f) => {
                  const active = filter === f.key;
                  const n = counts[f.key];
                  if (f.key !== "all" && n === 0) return null;
                  return (
                    <button
                      key={f.key}
                      onClick={() => setFilter(f.key)}
                      className={`px-2.5 py-1 text-mono text-[10px] tracking-[0.2em] uppercase rounded-lg transition-all shrink-0 ${
                        active
                          ? "bg-jarvis-cyan/15 text-jarvis-ice shadow-[0_0_20px_-4px_rgba(125,211,252,0.5)_inset] border border-jarvis-cyan/30"
                          : "text-jarvis-ice/40 hover:text-jarvis-ice hover:bg-jarvis-ice/[0.04] border border-transparent"
                      }`}
                    >
                      {f.label} <span className="opacity-50 ml-0.5">{n}</span>
                    </button>
                  );
                })}
              </div>
            )}

            <div className="flex items-center gap-1.5 shrink-0">
              <IconBtn onClick={openGalaxy} title="Open neural memory galaxy">⌬</IconBtn>
              <IconBtn onClick={openWebcam} title="Open webcam">◉</IconBtn>
              <IconBtn onClick={() => setCollapsed((c) => !c)} title={collapsed ? "Expand" : "Collapse"}>
                {collapsed ? "▾" : "▴"}
              </IconBtn>
              <IconBtn onClick={() => useStore.getState().clearMedia()} title="Clear bay" danger>×</IconBtn>
            </div>
          </div>
        </div>

        {/* ── Cards ─────────────────────────────────────────────── */}
        {!collapsed && (
          <div
            className="flex-1 overflow-y-auto p-4 space-y-3.5 scroll-smooth"
            onMouseLeave={() => setHover(null)}
          >
            <AnimatePresence mode="popLayout">
              {filtered.map((card) => {
                const dim = hover && hover !== card.id;
                return (
                  <motion.div
                    key={card.id}
                    layout
                    // Initial=false: MediaReveal owns the intro animation now,
                    // so the wrapper only handles dim / hover / exit transitions.
                    initial={false}
                    animate={{
                      opacity: dim ? 0.45 : 1,
                      y: 0,
                      scale: hover === card.id ? 1.003 : 1,
                      filter: dim ? "blur(0.4px) saturate(0.85)" : "none",
                    }}
                    exit={{ opacity: 0, y: -8, scale: 0.95 }}
                    transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                    onMouseEnter={() => setHover(card.id)}
                  >
                    <MediaReveal cardId={card.id} kind={card.kind}>
                      <Card
                        card={card}
                        onClose={() => removeMedia(card.id)}
                        onPin={(p) => pinMedia(card.id, p)}
                        onExpand={(idx) => expandMedia(card.id, idx)}
                        onMaximize={() => setMaximized(card.id)}
                        onLightbox={(kind, item) => setLightbox({ kind, item })}
                        hovered={hover === card.id}
                      />
                    </MediaReveal>
                  </motion.div>
                );
              })}
            </AnimatePresence>
            {filtered.length === 0 && (
              <div className="text-center text-mono text-[11px] text-jarvis-ice/35 py-8">
                no items in this view.
              </div>
            )}
          </div>
        )}
      </motion.div>

      {/* ── Maximised overlay ─────────────────────────────────────── */}
      <AnimatePresence>
        {maxCard && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[150] flex items-center justify-center p-6"
            style={{ background: "rgba(3,7,15,0.78)", backdropFilter: "blur(20px) saturate(140%)" }}
            onClick={() => setMaximized(null)}
          >
            <motion.div
              initial={{ scale: 0.96, y: 18, opacity: 0 }}
              animate={{ scale: 1, y: 0, opacity: 1 }}
              exit={{ scale: 0.96, y: 18, opacity: 0 }}
              transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
              className={
                maxIsModel3D
                  ? "w-[92vw] h-[88vh] flex flex-col overflow-visible"
                  : "holo-panel w-[92vw] h-[88vh] flex flex-col overflow-hidden"
              }
              onClick={(e) => e.stopPropagation()}
            >
              {!maxIsModel3D && (
                <div className="panel-header flex items-center justify-between px-4 py-2.5 shrink-0">
                <div className="flex items-center gap-2.5 min-w-0">
                  <KindBadge kind={maxCard.kind} />
                  <span className="text-mono text-[12px] text-jarvis-ice truncate">
                    {maxCard.query ? `"${maxCard.query}"` : maxCard.summary}
                  </span>
                </div>
                <button
                  onClick={() => setMaximized(null)}
                  className="glass-chip hover:bg-jarvis-cyan/10 hover:text-jarvis-ice transition-colors"
                >
                  close · esc
                </button>
                </div>
              )}
              <div className={maxIsModel3D ? "flex-1 overflow-visible p-0" : "flex-1 overflow-y-auto p-5"}>
                <Card
                  card={maxCard}
                  onClose={() => { removeMedia(maxCard.id); setMaximized(null); }}
                  onPin={(p) => pinMedia(maxCard.id, p)}
                  onExpand={(idx) => expandMedia(maxCard.id, idx)}
                  onMaximize={() => setMaximized(null)}
                  onLightbox={(kind, item) => setLightbox({ kind, item })}
                  large
                  hovered
                />
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

/* ═════════════ Card shell ═════════════ */
function Card({
  card, onClose, onPin, onExpand, onMaximize, onLightbox, large = false, hovered = false,
}: {
  card: MediaCard;
  onClose: () => void;
  onPin: (v: boolean) => void;
  onExpand: (idx: number | null) => void;
  onMaximize: () => void;
  onLightbox: (kind: any, item: MediaItem) => void;
  large?: boolean;
  hovered?: boolean;
}) {
  const isModel3D = card.kind === "model3d";
  const shellStyle = isModel3D
    ? {
        background: "transparent",
        backdropFilter: "none",
        WebkitBackdropFilter: "none",
        border: "1px solid transparent",
        boxShadow: "none",
      }
    : {
        background: "rgba(14, 24, 42, 0.32)",
        backdropFilter: "blur(14px) saturate(150%)",
        WebkitBackdropFilter: "blur(14px) saturate(150%)",
        border: `1px solid ${hovered ? "rgba(186,230,253,0.28)" : "rgba(186,230,253,0.08)"}`,
        boxShadow: hovered
          ? "0 1px 0 0 rgba(255,255,255,0.08) inset, 0 12px 32px -8px rgba(0,0,0,0.5), 0 0 32px -8px rgba(125,211,252,0.25)"
          : "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 4px 12px -4px rgba(0,0,0,0.35)",
      };

  return (
    <div
      className={`relative transition-all duration-500 ${
        isModel3D ? "overflow-visible" : "rounded-xl overflow-hidden"
      } ${large ? "h-full flex flex-col" : ""}`}
      style={shellStyle}
    >
      {card.pinned && !large && (
        <div className="absolute top-2 left-2 z-20 glass-chip text-jarvis-aqua border-jarvis-aqua/40 bg-jarvis-aqua/15">
          PINNED
        </div>
      )}
      <div
        className={
          isModel3D
            ? "absolute top-2 left-2 right-2 z-30 flex items-center justify-between gap-2 rounded-full border border-jarvis-aqua/15 bg-jarvis-ink/35 px-3 py-1.5 backdrop-blur-md"
            : "panel-header flex items-center justify-between gap-2 px-3 py-1.5 shrink-0"
        }
      >
        <div className="flex items-center gap-2 min-w-0">
          <KindBadge kind={card.kind} />
          <span className="text-mono text-[11.5px] text-jarvis-ice/90 truncate">
            {card.query ? `"${card.query}"` : card.summary || card.tool}
          </span>
          <span className="text-mono text-[9.5px] text-jarvis-ice/40 shrink-0">
            {card.items.length} ·{" "}
            {new Date(card.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <IconBtn onClick={() => onPin(!card.pinned)} title={card.pinned ? "Unpin" : "Pin"}>
            {card.pinned ? "★" : "☆"}
          </IconBtn>
          {!large && <IconBtn onClick={onMaximize} title="Maximise">⛶</IconBtn>}
          <IconBtn onClick={onClose} title="Dismiss" danger>×</IconBtn>
        </div>
      </div>

      <div
        className={
          isModel3D
            ? `${large ? "flex-1 " : ""}overflow-visible p-0 pt-8`
            : `p-4 ${large ? "flex-1 overflow-y-auto" : "overflow-y-auto"}`
        }
        style={isModel3D || large ? undefined : { maxHeight: "min(180px, 18vh)" }}
      >
        {card.kind === "search" && (
          <SearchGrid items={card.items} onPick={(it) => onLightbox("page", it)} large={large} />
        )}
        {(card.kind === "image" || card.kind === "images") && (
          <ImageMasonry items={card.items} onPick={(it) => onLightbox("image", it)} large={large} />
        )}
        {(card.kind === "video" || card.kind === "videos") && (
          <VideoGrid items={card.items} expanded={card.expanded ?? null} onExpand={onExpand} large={large} />
        )}
        {card.kind === "page" && <PageEmbed item={card.items[0]} large={large} />}
        {card.kind === "webcam" && <WebcamFeed item={card.items[0]} large={large} />}
        {card.kind === "galaxy" && <NeuralGalaxy card={card} large={large} />}
        {card.kind === "model3d" && <Model3DViewer item={card.items[0]} large={large} />}
      </div>
    </div>
  );
}

/* ═════════════ Per-item motion variants — dramatic JARVIS in ═════════════ */

// All grids share this container — slightly slower stagger so the holographic
// reveal of the parent card has space to breathe before items start flying in.
const cascadeContainer = {
  hidden: {},
  show:   { transition: { staggerChildren: 0.055, delayChildren: 0.55 } },
};

// Search rows: streak in from the right with chromatic blur, a slight 3D
// pre-tilt, and an overshoot settle. Reads as "result deserialised".
const cascadeFromRight = {
  hidden: { opacity: 0, x: 40, rotateY: -16, filter: "blur(8px) brightness(1.4)" },
  show:   {
    opacity: 1, x: 0, rotateY: 0, filter: "blur(0px) brightness(1)",
    transition: {
      duration: 0.6,
      ease: [0.16, 1, 0.3, 1] as any,
      filter: { duration: 0.45 },
    },
  },
};

// Image / video tiles: pop in with 3D rotate-x, scale overshoot, blur-sharp.
// Reads as "photo print developing on a glass plate".
const tileItem = {
  hidden: { opacity: 0, y: 22, scale: 0.78, rotateX: -22, filter: "blur(10px) brightness(1.55)" },
  show: {
    opacity: 1, y: 0, scale: 1, rotateX: 0, filter: "blur(0px) brightness(1)",
    transition: {
      duration: 0.7,
      ease: [0.16, 1, 0.3, 1] as any,
      filter:  { duration: 0.55 },
      scale:   { duration: 0.7, type: "spring" as const, stiffness: 140, damping: 14 },
    },
  },
};

function SearchGrid({ items, onPick, large }: { items: MediaItem[]; onPick: (it: MediaItem) => void; large: boolean }) {
  const minRow = large ? 400 : 340;
  return (
    <motion.ul
      className="relative grid gap-2"
      style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${minRow}px, 1fr))` }}
      variants={cascadeContainer}
      initial="hidden"
      animate="show"
    >
      {items.map((it, i) => (
        <motion.li key={i} variants={cascadeFromRight} layout style={{ perspective: 800 }}>
          <button
            onClick={() => onPick(it)}
            className="w-full group relative flex items-start gap-3 p-3 rounded-xl text-left transition-all overflow-hidden border border-transparent hover:border-jarvis-cyan/25"
            style={{ background: "rgba(14,24,42,0.28)" }}
          >
            {/* Left-edge cyan beam that lights up as the row deserialises */}
            <motion.div
              className="absolute left-0 top-0 bottom-0 w-[2px]"
              style={{
                background: "linear-gradient(180deg, transparent, rgba(186,230,253,0.95), transparent)",
                boxShadow: "0 0 12px rgba(125,211,252,0.85)",
              }}
              initial={{ scaleY: 0, opacity: 0 }}
              animate={{ scaleY: [0, 1, 1, 0], opacity: [0, 1, 1, 0] }}
              transition={{ duration: 0.9, delay: 0.55 + i * 0.055, ease: "easeOut", times: [0, 0.25, 0.7, 1] }}
            />

            <div className="relative shrink-0">
              {it.thumbnail ? (
                <img
                  src={it.thumbnail} alt="" referrerPolicy="no-referrer"
                  className="w-10 h-10 object-contain bg-jarvis-cyan/5 rounded-lg p-1 border border-jarvis-cyan/10"
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                />
              ) : (
                <div className="w-10 h-10 rounded-lg bg-jarvis-cyan/5 border border-jarvis-cyan/10 flex items-center justify-center text-mono text-[10px] text-jarvis-ice/50">
                  WEB
                </div>
              )}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px] text-jarvis-ice group-hover:text-shimmer truncate font-medium">{it.title || it.url}</div>
              {it.snippet && (
                <div className="text-[11px] text-jarvis-ice/55 line-clamp-2 mt-1 leading-relaxed">{it.snippet}</div>
              )}
              <div className="flex items-center gap-2 mt-1.5">
                <span className="text-mono text-[9.5px] text-jarvis-cyan/65 truncate">
                  {it.source || hostFromUrl(it.url)}
                </span>
              </div>
            </div>
            <span className="absolute right-3 top-3 text-jarvis-ice/0 group-hover:text-jarvis-aqua text-sm transition-all group-hover:translate-x-0.5">↗</span>
            <ItemFlash delay={0.55 + i * 0.055} />
          </button>
        </motion.li>
      ))}
    </motion.ul>
  );
}

/* ═════════════ Image masonry — glass tiles, soft float ═════════════ */
const imageContainer = cascadeContainer;
const imageItem = tileItem;

/* ═════════════ Reusable per-item flash overlay ═════════════
 *
 * Single-shot cyan corner-tick flash + diagonal sheen that fires when a
 * grid item appears. Self-times via setTimeout — runs once per mount.
 */
function ItemFlash({ delay = 0, full = false }: { delay?: number; full?: boolean }) {
  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden rounded-xl">
      {/* Corner ticks: 4 little cyan L-brackets that snap in then fade */}
      {(["tl", "tr", "bl", "br"] as const).map((corner) => {
        const isLeft = corner === "tl" || corner === "bl";
        const isTop  = corner === "tl" || corner === "tr";
        return (
          <motion.div
            key={corner}
            className="absolute w-3.5 h-3.5"
            style={{
              top:    isTop  ? 4 : "auto",
              bottom: !isTop ? 4 : "auto",
              left:   isLeft ? 4 : "auto",
              right:  !isLeft ? 4 : "auto",
              borderTop:    isTop  ? "1.5px solid rgba(186,230,253,0.95)" : "none",
              borderBottom: !isTop ? "1.5px solid rgba(186,230,253,0.95)" : "none",
              borderLeft:   isLeft ? "1.5px solid rgba(186,230,253,0.95)" : "none",
              borderRight:  !isLeft ? "1.5px solid rgba(186,230,253,0.95)" : "none",
              filter: "drop-shadow(0 0 4px rgba(125,211,252,0.85))",
            }}
            initial={{ opacity: 0, scale: 1.8 }}
            animate={{ opacity: [0, 1, 0], scale: [1.8, 1, 0.9] }}
            transition={{ duration: 0.6, delay: delay + 0.1, ease: "easeOut", times: [0, 0.35, 1] }}
          />
        );
      })}

      {/* Diagonal sheen: a single bright streak crossing the tile */}
      <motion.div
        className="absolute"
        style={{
          top: 0, left: 0,
          width: "200%", height: "200%",
          background:
            "linear-gradient(115deg, transparent 35%, rgba(186,230,253,0.55) 48%, rgba(186,230,253,0.95) 50%, rgba(186,230,253,0.55) 52%, transparent 65%)",
          filter: "blur(1.2px)",
          mixBlendMode: "screen",
        }}
        initial={{ x: "-110%", y: "-110%", opacity: 0 }}
        animate={{ x: "10%", y: "10%", opacity: [0, 0.95, 0] }}
        transition={{ duration: 0.9, delay, ease: "easeOut", times: [0, 0.35, 1] }}
      />

      {/* Optional full-frame white flash on appear — used for image/video */}
      {full && (
        <motion.div
          className="absolute inset-0"
          style={{ background: "rgba(186,230,253,0.7)", mixBlendMode: "screen" }}
          initial={{ opacity: 0 }}
          animate={{ opacity: [0, 0.55, 0] }}
          transition={{ duration: 0.32, delay, ease: "easeOut", times: [0, 0.15, 1] }}
        />
      )}
    </div>
  );
}

function ImageMasonry({ items, onPick, large }: { items: MediaItem[]; onPick: (it: MediaItem) => void; large: boolean }) {
  if (!large && items.length === 1) {
    const it = items[0];
    return (
      <motion.div
        className="relative overflow-hidden rounded-xl group cursor-pointer"
        style={{
          background: "rgba(14,24,42,0.35)",
          border: "1px solid rgba(186,230,253,0.08)",
          aspectRatio: "16 / 10",
          maxHeight: 240,
          perspective: 800,
        }}
        variants={tileItem}
        initial="hidden"
        animate="show"
        onClick={() => onPick(it)}
        whileHover={{ scale: 1.01, transition: { duration: 0.25 } }}
        title={it.title || ""}
      >
        {/* Image starts grayscale + blurred + bright then "develops" to full colour. */}
        <motion.img
          src={it.thumbnail || it.url}
          alt={it.title || ""}
          referrerPolicy="no-referrer"
          loading="lazy"
          className="absolute inset-0 w-full h-full object-contain"
          initial={{ filter: "grayscale(1) blur(10px) brightness(1.6) contrast(0.7)", scale: 1.08 }}
          animate={{ filter: "grayscale(0) blur(0px) brightness(1) contrast(1)", scale: 1 }}
          transition={{ duration: 0.95, delay: 0.6, ease: [0.16, 1, 0.3, 1] }}
          onError={(e) => { (e.currentTarget as HTMLImageElement).style.opacity = "0.25"; }}
        />
        <div className="absolute inset-0 pointer-events-none bg-gradient-to-t from-jarvis-ink/70 via-transparent to-transparent" />
        {(it.title || it.snippet) && (
          <div className="absolute inset-x-0 bottom-0 px-3 py-2">
            <div className="text-[11px] text-jarvis-ice/90 truncate">{it.title || it.snippet}</div>
          </div>
        )}
        <ItemFlash delay={0.55} full />
      </motion.div>
    );
  }

  const minTile = large ? 180 : 150;
  return (
    <motion.div
      className="relative grid gap-3"
      style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${minTile}px, 1fr))` }}
      variants={imageContainer}
      initial="hidden"
      animate="show"
    >
      {items.map((it, i) => {
        const itemDelay = 0.55 + i * 0.055;
        return (
          <motion.button
            key={i}
            variants={tileItem}
            onClick={() => onPick(it)}
            whileHover={{ scale: 1.04, y: -3, transition: { duration: 0.28, ease: [0.16, 1, 0.3, 1] } }}
            whileTap={{ scale: 0.97 }}
            className="relative aspect-square overflow-hidden group rounded-xl"
            style={{
              background: "rgba(14,24,42,0.35)",
              border: "1px solid rgba(186,230,253,0.08)",
              transformOrigin: "center",
              boxShadow: "0 4px 12px -4px rgba(0,0,0,0.4)",
              perspective: 800,
            }}
            title={it.title || ""}
          >
            <motion.img
              src={it.thumbnail || it.url}
              alt={it.title || ""}
              referrerPolicy="no-referrer"
              loading="lazy"
              className="absolute inset-0 w-full h-full object-cover transition-transform duration-700 group-hover:scale-[1.12]"
              initial={{ filter: "grayscale(1) blur(8px) brightness(1.5)", scale: 1.1 }}
              animate={{ filter: "grayscale(0) blur(0px) brightness(1)", scale: 1 }}
              transition={{ duration: 0.85, delay: itemDelay, ease: [0.16, 1, 0.3, 1] }}
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.opacity = "0.25"; }}
            />
            <div className="absolute inset-0 pointer-events-none bg-gradient-to-t from-jarvis-ink/75 via-transparent to-transparent" />
            <div className="absolute inset-0 rounded-xl pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-300"
                 style={{ boxShadow: "0 0 0 1px rgba(186,230,253,0.45) inset, 0 0 24px -4px rgba(125,211,252,0.45)" }} />
            {(it.title || it.host) && (
              <div className="absolute inset-x-0 bottom-0 px-2 py-1 opacity-90 group-hover:opacity-100 transition-opacity">
                <div className="text-[10px] text-jarvis-ice truncate">
                  {it.title || hostFromUrl(it.host || "")}
                </div>
              </div>
            )}
            <ItemFlash delay={itemDelay} full />
          </motion.button>
        );
      })}
    </motion.div>
  );
}

/* ═════════════ Videos — premium thumbnails ═════════════ */
const videoItem = tileItem;

function VideoGrid({
  items, expanded, onExpand, large,
}: { items: MediaItem[]; expanded: number | null; onExpand: (i: number | null) => void; large: boolean }) {
  if (expanded !== null && items[expanded]) {
    const v = items[expanded];
    return (
      <motion.div
        key={`exp-${expanded}`}
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="space-y-3"
      >
        <div className="relative w-full aspect-video bg-black rounded-xl overflow-hidden"
             style={{
               border: "1px solid rgba(186,230,253,0.18)",
               boxShadow: "0 0 0 1px rgba(125,211,252,0.08) inset, 0 16px 48px -16px rgba(0,0,0,0.7), 0 0 32px -8px rgba(125,211,252,0.25)",
             }}>
          <iframe
            src={`${v.embed_url}?autoplay=1&rel=0`}
            title={v.title}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
            className="absolute inset-0 w-full h-full"
          />
        </div>
        <div className="flex items-baseline justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[13px] text-jarvis-ice font-medium truncate">{v.title}</div>
            <div className="text-mono text-[10px] text-jarvis-ice/55 truncate mt-0.5">
              {v.channel}{v.duration ? ` · ${v.duration}` : ""}{v.views ? ` · ${v.views}` : ""}{v.published ? ` · ${v.published}` : ""}
            </div>
          </div>
          <button
            onClick={() => onExpand(null)}
            className="glass-chip hover:bg-jarvis-cyan/10 hover:text-jarvis-ice transition-colors shrink-0"
          >
            ← gallery
          </button>
        </div>
        {items.length > 1 && (
          <div className="grid grid-cols-6 gap-1.5 pt-1">
            {items.map((v2, j) => (
              <button
                key={j}
                onClick={() => onExpand(j)}
                className={`relative aspect-video rounded-md overflow-hidden transition-all ${
                  j === expanded
                    ? "ring-1 ring-jarvis-aqua/70 shadow-[0_0_12px_-2px_rgba(165,243,252,0.5)]"
                    : "border border-jarvis-ice/10 hover:border-jarvis-cyan/40"
                }`}
              >
                <img src={v2.thumbnail || ""} alt="" referrerPolicy="no-referrer" loading="lazy" className="w-full h-full object-cover" />
              </button>
            ))}
          </div>
        )}
      </motion.div>
    );
  }
  const minTile = large ? 260 : 230;
  return (
    <motion.div
      className="relative grid gap-3"
      style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${minTile}px, 1fr))` }}
      variants={imageContainer}
      initial="hidden"
      animate="show"
    >
      {items.map((v, i) => {
        const itemDelay = 0.55 + i * 0.055;
        return (
          <motion.button
            key={i}
            variants={videoItem}
            whileHover={{ y: -4, scale: 1.025, transition: { duration: 0.28, ease: [0.16, 1, 0.3, 1] } }}
            whileTap={{ scale: 0.97 }}
            onClick={() => onExpand(i)}
            className="relative text-left overflow-hidden group rounded-xl"
            style={{
              background: "rgba(14,24,42,0.32)",
              border: "1px solid rgba(186,230,253,0.08)",
              boxShadow: "0 4px 14px -4px rgba(0,0,0,0.4)",
              perspective: 800,
            }}
          >
            <div className="relative w-full aspect-video overflow-hidden">
              {/* Thumbnail: tunes in like an old TV channel — desat + scaled */}
              <motion.img
                src={v.thumbnail || ""}
                alt={v.title || ""}
                referrerPolicy="no-referrer"
                loading="lazy"
                className="absolute inset-0 w-full h-full object-cover group-hover:scale-[1.10] transition-transform duration-700"
                initial={{ filter: "grayscale(1) blur(8px) brightness(1.4) contrast(0.6)", scale: 1.12 }}
                animate={{ filter: "grayscale(0) blur(0px) brightness(1) contrast(1)", scale: 1 }}
                transition={{ duration: 0.9, delay: itemDelay, ease: [0.16, 1, 0.3, 1] }}
              />
              <div className="absolute inset-0 bg-gradient-to-t from-jarvis-ink/85 via-transparent to-transparent" />

              {/* CRT channel-lock scanline that sweeps once on appear */}
              <motion.div
                className="absolute inset-x-0 h-[2px] pointer-events-none"
                style={{
                  background: "linear-gradient(90deg, transparent, rgba(186,230,253,0.95), transparent)",
                  boxShadow: "0 0 14px rgba(125,211,252,0.85), 0 0 4px rgba(186,230,253,1)",
                  mixBlendMode: "screen",
                }}
                initial={{ top: "-4%", opacity: 0 }}
                animate={{ top: ["-4%", "100%"], opacity: [0, 1, 1, 0] }}
                transition={{ duration: 0.95, delay: itemDelay, ease: "easeOut", times: [0, 0.1, 0.85, 1] }}
              />

              <motion.div
                className="absolute inset-0 flex items-center justify-center"
                animate={{ scale: [1, 1.08, 1] }}
                transition={{ duration: 2.6, repeat: Infinity, ease: "easeInOut" }}
              >
                <div
                  className="w-14 h-14 rounded-full flex items-center justify-center transition-all group-hover:scale-110"
                  style={{
                    background: "linear-gradient(135deg, rgba(165,243,252,0.95), rgba(125,211,252,0.9))",
                    boxShadow:
                      "0 0 0 1px rgba(255,255,255,0.3) inset, 0 8px 24px -4px rgba(125,211,252,0.7), 0 0 40px -4px rgba(167,139,250,0.4)",
                  }}
                >
                  <span className="text-jarvis-abyss text-lg translate-x-0.5">▶</span>
                </div>
              </motion.div>
              {v.duration && (
                <div className="absolute bottom-2 right-2 glass-chip">
                  {v.duration}
                </div>
              )}
              <div className="absolute inset-0 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-300"
                   style={{ boxShadow: "0 0 0 1px rgba(186,230,253,0.45) inset, 0 0 32px -4px rgba(125,211,252,0.4)" }} />
              <ItemFlash delay={itemDelay} full />
            </div>
            <div className="px-3 py-2">
              <div className="text-[11.5px] text-jarvis-ice line-clamp-2 leading-snug group-hover:text-shimmer transition-colors font-medium">
                {v.title}
              </div>
              <div className="text-mono text-[9.5px] text-jarvis-ice/45 truncate mt-1">{v.channel}</div>
            </div>
          </motion.button>
        );
      })}
    </motion.div>
  );
}

/* ═════════════ Page embed — glass frame ═════════════ */
function PageEmbed({ item, large }: { item: MediaItem; large: boolean }) {
  if (!item?.url) return null;
  const proxied = `/api/proxy?url=${encodeURIComponent(item.url)}`;
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="space-y-2"
    >
      <div className="flex items-center gap-2 text-mono text-[10px] px-1">
        <span className="glass-chip text-jarvis-aqua border-jarvis-aqua/30">URL</span>
        <span className="truncate flex-1 text-jarvis-ice/70">{item.url}</span>
        <a
          href={item.url.startsWith("http") ? item.url : `https://${item.url}`}
          target="_blank" rel="noreferrer noopener"
          className="glass-chip hover:bg-jarvis-cyan/10 hover:text-jarvis-ice transition-colors"
        >
          open ↗
        </a>
      </div>
      <div className={`relative w-full rounded-xl overflow-hidden ${large ? "h-[72vh]" : "h-[58vh]"}`}
           style={{ border: "1px solid rgba(186,230,253,0.15)", boxShadow: "0 12px 36px -12px rgba(0,0,0,0.6)" }}>
        <iframe
          src={proxied}
          title={item.title || item.url}
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation"
          referrerPolicy="no-referrer"
          className="absolute inset-0 w-full h-full bg-white"
        />
      </div>
    </motion.div>
  );
}

/* ═════════════ Bits ═════════════ */
function KindBadge({ kind }: { kind: MediaKind }) {
  const map: Record<string, { label: string; bg: string; border: string; text: string }> = {
    search: { label: "WEB",    bg: "rgba(125,211,252,0.12)", border: "rgba(125,211,252,0.40)", text: "#7dd3fc" },
    image:  { label: "IMAGE",  bg: "rgba(165,243,252,0.12)", border: "rgba(165,243,252,0.40)", text: "#a5f3fc" },
    images: { label: "IMAGES", bg: "rgba(165,243,252,0.12)", border: "rgba(165,243,252,0.40)", text: "#a5f3fc" },
    video:  { label: "VIDEO",  bg: "rgba(251,191,36,0.12)",  border: "rgba(251,191,36,0.40)",  text: "#fbbf24" },
    videos: { label: "VIDEOS", bg: "rgba(251,191,36,0.12)",  border: "rgba(251,191,36,0.40)",  text: "#fbbf24" },
    page:   { label: "PAGE",   bg: "rgba(186,230,253,0.12)", border: "rgba(186,230,253,0.40)", text: "#bae6fd" },
    pdf:    { label: "PDF",    bg: "rgba(186,230,253,0.12)", border: "rgba(186,230,253,0.40)", text: "#bae6fd" },
    webcam: { label: "CAM",    bg: "rgba(251,113,133,0.12)", border: "rgba(251,113,133,0.40)", text: "#fb7185" },
    galaxy: { label: "MEMORY", bg: "rgba(167,139,250,0.14)", border: "rgba(167,139,250,0.40)", text: "#a78bfa" },
    model3d:{ label: "3D",     bg: "rgba(186,230,253,0.12)", border: "rgba(186,230,253,0.40)", text: "#bae6fd" },
  };
  const c = map[kind] || map.search;
  return (
    <span
      className="text-mono text-[9px] tracking-[0.2em] font-medium px-1.5 py-0.5 rounded-md uppercase"
      style={{ background: c.bg, border: `1px solid ${c.border}`, color: c.text }}
    >
      {c.label}
    </span>
  );
}

function IconBtn({
  children, onClick, title, danger = false,
}: { children: React.ReactNode; onClick: () => void; title?: string; danger?: boolean }) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`w-7 h-7 flex items-center justify-center rounded-lg text-[12px] transition-all border ${
        danger
          ? "border-transparent text-jarvis-ice/50 hover:text-jarvis-danger hover:border-jarvis-danger/40 hover:bg-jarvis-danger/10"
          : "border-transparent text-jarvis-ice/55 hover:text-jarvis-ice hover:border-jarvis-cyan/30 hover:bg-jarvis-cyan/10"
      }`}
    >
      {children}
    </button>
  );
}

function hostFromUrl(u: string): string {
  try { return new URL(u).hostname; } catch { return u; }
}
