/**
 * FLOATING — generic draggable + resizable panel wrapper.
 *
 * Persistence rules (the source of every "my layout vanished" bug):
 *   • localStorage is written ONLY on user-intent (drag end, resize end,
 *     page unload). Window resize does NOT mutate persisted state — it
 *     just re-derives the displayed position visually.
 *   • Saved record includes the viewport dimensions AT THE TIME OF SAVE
 *     so we can detect the user's intended anchor (left / right / center /
 *     bottom) and re-place the panel correctly when the window grows or
 *     shrinks later.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  collidesAnything,
  findSlot,
  release as releaseSlot,
  update as updateSlot,
} from "../../lib/layoutBroker";

export interface Box { x: number; y: number; w: number; h: number }
interface SavedBox extends Box { vw?: number; vh?: number }

interface Props {
  id: string;
  defaultBox: Box;
  minW?: number;
  minH?: number;
  children: React.ReactNode;
  /** disable drag/resize (read-only layout slot) */
  locked?: boolean;
  /** z-index when focused */
  z?: number;
  /** track content height — disables vertical resize, height auto-grows */
  autoHeight?: boolean;
}

const STORAGE_PREFIX = "jarvis.floating.v2.";
const ANCHOR_PX = 96;

function loadStoredBox(id: string): SavedBox | null {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + id);
    if (!raw) return null;
    const b = JSON.parse(raw);
    if (
      typeof b?.x === "number" &&
      typeof b?.y === "number" &&
      typeof b?.w === "number" &&
      typeof b?.h === "number"
    ) {
      return b;
    }
  } catch { /* ignore */ }
  return null;
}

function loadBox(id: string, fallback: Box): SavedBox {
  // Existing user-intent layout wins ONLY if it doesn't collide with any
  // already-registered panel. If a stored layout would overlap something
  // already live the broker overrides it with the first free slot — the
  // user's "everything in its own window" rule trumps the saved layout.
  const stored = loadStoredBox(id);
  const vw = typeof window !== "undefined" ? window.innerWidth : 1600;
  const vh = typeof window !== "undefined" ? window.innerHeight : 900;
  if (stored) {
    const display = computeDisplay(stored, vw, vh);
    if (!collidesAnything(id, display)) {
      updateSlot(id, display);
      return stored;
    }
    // Stored position would overlap a live neighbour — fall through to the
    // broker so we find a clear slot. Use stored size as the request hint
    // so the user's preferred dimensions survive.
  }
  const slot = findSlot(id, stored ?? fallback, vw, vh);
  updateSlot(id, slot);
  return { ...slot, vw, vh };
}

function saveBox(id: string, box: Box) {
  const record: SavedBox = {
    ...box,
    vw: typeof window !== "undefined" ? window.innerWidth : undefined,
    vh: typeof window !== "undefined" ? window.innerHeight : undefined,
  };
  try { localStorage.setItem(STORAGE_PREFIX + id, JSON.stringify(record)); } catch { /* ignore */ }
}

export function resetAllLayouts() {
  try {
    Object.keys(localStorage)
      .filter((k) => k.startsWith(STORAGE_PREFIX) || k.startsWith("jarvis.floating.v1."))
      .forEach((k) => localStorage.removeItem(k));
    // Wipe broker so the reload-rendered panels re-pack from scratch.
    window.location.reload();
  } catch { /* ignore */ }
}

/**
 * Given the saved box and the CURRENT viewport, return the display position.
 * The saved viewport (vw,vh) lets us decide which edge the user originally
 * anchored to and follow it visually as the window resizes.
 */
function computeDisplay(saved: SavedBox, vw: number, vh: number): Box {
  const w = Math.min(saved.w, Math.max(80, vw - 16));
  const h = Math.min(saved.h, Math.max(60, vh - 16));

  // Without a saved viewport we just clamp the raw coordinates.
  if (!saved.vw || !saved.vh) {
    return {
      x: Math.max(0, Math.min(vw - 80, saved.x)),
      y: Math.max(0, Math.min(vh - 60, saved.y)),
      w,
      h,
    };
  }

  // Horizontal placement.
  const rightGap = saved.vw - (saved.x + saved.w);
  const centerOff = (saved.x + saved.w / 2) - saved.vw / 2;
  let x = saved.x;
  if (rightGap >= 0 && rightGap <= ANCHOR_PX && saved.x > ANCHOR_PX) {
    x = vw - w - rightGap;
  } else if (Math.abs(centerOff) <= ANCHOR_PX && saved.x > ANCHOR_PX) {
    x = vw / 2 - w / 2 + centerOff;
  }

  // Vertical placement.
  const bottomGap = saved.vh - (saved.y + saved.h);
  let y = saved.y;
  if (bottomGap >= 0 && bottomGap <= ANCHOR_PX && saved.y > ANCHOR_PX) {
    y = vh - h - bottomGap;
  }

  return {
    x: Math.max(0, Math.min(vw - 80, x)),
    y: Math.max(0, Math.min(vh - 60, y)),
    w,
    h,
  };
}

export default function Floating({
  id,
  defaultBox,
  minW = 240,
  minH = 120,
  children,
  locked = false,
  z = 20,
  autoHeight = false,
}: Props) {
  // `saved` is the user-intent box (only mutated by drag/resize end).
  const [saved, setSaved] = useState<SavedBox>(() => loadBox(id, defaultBox));
  // `vp` tracks the live viewport so render can re-derive position.
  const [vp, setVp] = useState(() => ({
    w: typeof window !== "undefined" ? window.innerWidth : 1600,
    h: typeof window !== "undefined" ? window.innerHeight : 900,
  }));
  // `transient` overrides `saved` during an active drag / resize so the
  // panel follows the pointer without writing localStorage until release.
  const [transient, setTransient] = useState<Box | null>(null);

  const [focused, setFocused] = useState(false);
  const dragRef = useRef<{ startX: number; startY: number; orig: Box } | null>(null);
  const resizeRef = useRef<{ startX: number; startY: number; orig: Box } | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // Window resize — update viewport state ONLY. Do not touch saved.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      raf = 0;
      setVp({ w: window.innerWidth, h: window.innerHeight });
    };
    const onResize = () => {
      if (raf) return;
      raf = requestAnimationFrame(tick);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  // Flush on page hide/close — last line of defense against lost layout.
  useEffect(() => {
    const flush = () => saveBox(id, transient ?? saved);
    window.addEventListener("beforeunload", flush);
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("beforeunload", flush);
      window.removeEventListener("pagehide", flush);
    };
  }, [id, saved, transient]);

  // Auto-track content height when autoHeight=true. Only writes saved height
  // when content height stabilises — never on transient drag.
  useEffect(() => {
    if (!autoHeight || !contentRef.current) return;
    const el = contentRef.current;
    const ro = new ResizeObserver((entries) => {
      for (const ent of entries) {
        const h = Math.ceil(ent.contentRect.height);
        if (h > 0) {
          setSaved((b) => (Math.abs(b.h - h) < 2 ? b : { ...b, h }));
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [autoHeight]);

  // Persist saved layout whenever it changes — but only for USER-intent
  // changes (drag/resize end + autoHeight settle). Window-resize never
  // touches `saved` so this effect doesn't fire on window resize.
  useEffect(() => {
    saveBox(id, saved);
  }, [id, saved]);

  // ── Render geometry. Either pointer-driven (transient) or derived from
  // saved + current viewport.
  const display = useMemo(() => {
    if (transient) return transient;
    return computeDisplay(saved, vp.w, vp.h);
  }, [saved, vp, transient]);

  // Publish current display rect to the broker so newly-spawned panels can
  // find a non-overlapping slot relative to where everything actually sits.
  useEffect(() => {
    updateSlot(id, display);
  }, [id, display.x, display.y, display.w, display.h]);

  useEffect(() => () => releaseSlot(id), [id]);

  // ── Drag ──────────────────────────────────────────────────────────────
  const onDragStart = useCallback((e: React.PointerEvent) => {
    if (locked) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    dragRef.current = { startX: e.clientX, startY: e.clientY, orig: { ...display } };
    setTransient({ ...display });
    setFocused(true);
  }, [locked, display]);

  const onDragMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    setTransient({
      ...dragRef.current.orig,
      x: Math.max(0, Math.min(window.innerWidth  - 80, dragRef.current.orig.x + dx)),
      y: Math.max(0, Math.min(window.innerHeight - 60, dragRef.current.orig.y + dy)),
    });
  }, []);

  const onDragEnd = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current) return;
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    dragRef.current = null;
    setTransient((t) => {
      if (t) {
        setSaved({ ...t, vw: window.innerWidth, vh: window.innerHeight });
      }
      return null;
    });
  }, []);

  // ── Resize ────────────────────────────────────────────────────────────
  const onResizeStart = useCallback((e: React.PointerEvent) => {
    if (locked) return;
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    resizeRef.current = { startX: e.clientX, startY: e.clientY, orig: { ...display } };
    setTransient({ ...display });
    setFocused(true);
  }, [locked, display]);

  const onResizeMove = useCallback((e: React.PointerEvent) => {
    if (!resizeRef.current) return;
    const dx = e.clientX - resizeRef.current.startX;
    const dy = e.clientY - resizeRef.current.startY;
    setTransient({
      x: resizeRef.current.orig.x,
      y: resizeRef.current.orig.y,
      w: Math.max(minW, resizeRef.current.orig.w + dx),
      h: Math.max(minH, resizeRef.current.orig.h + dy),
    });
  }, [minW, minH]);

  const onResizeEnd = useCallback((e: React.PointerEvent) => {
    if (!resizeRef.current) return;
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    resizeRef.current = null;
    setTransient((t) => {
      if (t) {
        setSaved({ ...t, vw: window.innerWidth, vh: window.innerHeight });
      }
      return null;
    });
  }, []);

  return (
    <div
      data-floating-id={id}
      onPointerDown={() => setFocused(true)}
      onMouseEnter={() => setFocused(true)}
      onMouseLeave={() => setFocused(false)}
      className="animate-boot_in fixed pointer-events-auto"
      style={{
        left: display.x,
        top: display.y,
        width: display.w,
        height: autoHeight ? undefined : display.h,
        zIndex: focused ? z + 5 : z,
      }}
    >
      {!locked && (
        <div
          onPointerDown={onDragStart}
          onPointerMove={onDragMove}
          onPointerUp={onDragEnd}
          onPointerCancel={onDragEnd}
          title="drag"
          className="absolute top-0 left-0 right-0 h-6 z-30 cursor-grab active:cursor-grabbing"
          style={{ touchAction: "none" }}
        >
          <div
            className="absolute left-1/2 -translate-x-1/2 top-1.5 flex gap-0.5 transition-opacity"
            style={{ opacity: focused ? 0.65 : 0 }}
          >
            <span className="w-1 h-1 rounded-full bg-jarvis-ice/70" />
            <span className="w-1 h-1 rounded-full bg-jarvis-ice/70" />
            <span className="w-1 h-1 rounded-full bg-jarvis-ice/70" />
            <span className="w-1 h-1 rounded-full bg-jarvis-ice/70" />
            <span className="w-1 h-1 rounded-full bg-jarvis-ice/70" />
          </div>
        </div>
      )}

      <div
        ref={contentRef}
        style={{
          width: "100%",
          height: autoHeight ? "auto" : "100%",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {children}
      </div>

      {!locked && !autoHeight && (
        <div
          onPointerDown={onResizeStart}
          onPointerMove={onResizeMove}
          onPointerUp={onResizeEnd}
          onPointerCancel={onResizeEnd}
          title="resize"
          className="absolute bottom-0 right-0 w-4 h-4 z-30 cursor-nwse-resize group"
          style={{ touchAction: "none" }}
        >
          <div
            className="absolute bottom-1 right-1 transition-opacity"
            style={{ opacity: focused ? 0.7 : 0.25 }}
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
              <path d="M9 1 L1 9 M9 5 L5 9 M9 9 L9 9" stroke="rgba(186,230,253,0.85)" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
          </div>
        </div>
      )}
    </div>
  );
}
