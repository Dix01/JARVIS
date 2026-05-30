/**
 * LAYOUT BROKER — collision-free spawn placement for Floating panels.
 *
 * The Floating component asks the broker for a slot the first time a panel
 * appears (no saved localStorage entry). The broker scans a coarse grid
 * across the visible viewport and returns the first rectangle that does
 * not overlap any panel already live, with an 8 px breathing gap.
 *
 * After the initial placement every Floating reports its current display
 * rect on each render (`update(id, rect)`), and releases on unmount. The
 * broker therefore reflects the actual on-screen layout at all times, so
 * later-spawning panels avoid panels the user has dragged elsewhere.
 *
 * Reserved zones (eg. top bar / status bar) can be pushed via `reserve()`.
 */
export interface Rect { x: number; y: number; w: number; h: number }

const live: Map<string, Rect> = new Map();
const reserved: Rect[] = [];

const GAP = 8;
const SCAN_STEP = 24;
const TOP_MARGIN = 76;     // leave room for TopBar
const BOTTOM_MARGIN = 60;  // leave room for StatusBar
const SIDE_MARGIN = 16;

export function update(id: string, rect: Rect): void {
  live.set(id, rect);
}

export function release(id: string): void {
  live.delete(id);
}

export function reserve(zones: Rect[]): void {
  reserved.length = 0;
  reserved.push(...zones);
}

function overlaps(a: Rect, b: Rect): boolean {
  return !(
    a.x + a.w + GAP <= b.x ||
    b.x + b.w + GAP <= a.x ||
    a.y + a.h + GAP <= b.y ||
    b.y + b.h + GAP <= a.y
  );
}

function collisionFree(id: string, probe: Rect): boolean {
  for (const [otherId, r] of live) {
    if (otherId === id) continue;
    if (overlaps(probe, r)) return false;
  }
  for (const r of reserved) {
    if (overlaps(probe, r)) return false;
  }
  return true;
}

/**
 * Check whether a given rect collides with any live registered panel
 * (excluding self) or any reserved zone. Exposed so the Floating component
 * can decide to re-broker a stored layout that overlaps something newer.
 */
export function collidesAnything(id: string, rect: Rect): boolean {
  return !collisionFree(id, rect);
}

/**
 * Find a non-overlapping slot for `id`. Tries the requested rect first
 * (so the App.tsx defaults still drive rough placement); falls back to a
 * row-major grid scan; last resort cascades from the centre.
 */
export function findSlot(
  id: string,
  requested: Rect,
  vw: number,
  vh: number,
): Rect {
  const w = Math.min(requested.w, Math.max(120, vw - SIDE_MARGIN * 2));
  const h = Math.min(requested.h, Math.max(100, vh - TOP_MARGIN - BOTTOM_MARGIN));

  // 1) Requested position if it fits and is in-viewport.
  const req: Rect = { x: requested.x, y: requested.y, w, h };
  if (
    req.x >= SIDE_MARGIN &&
    req.y >= TOP_MARGIN &&
    req.x + req.w <= vw - SIDE_MARGIN &&
    req.y + req.h <= vh - BOTTOM_MARGIN &&
    collisionFree(id, req)
  ) {
    return req;
  }

  // 2) Row-major scan from top-left through the usable region.
  const maxX = vw - SIDE_MARGIN - w;
  const maxY = vh - BOTTOM_MARGIN - h;
  for (let cy = TOP_MARGIN; cy <= maxY; cy += SCAN_STEP) {
    for (let cx = SIDE_MARGIN; cx <= maxX; cx += SCAN_STEP) {
      const probe: Rect = { x: cx, y: cy, w, h };
      if (collisionFree(id, probe)) return probe;
    }
  }

  // 3) Last resort — cascade from centre with a per-instance offset so
  //    multiple fallbacks don't stack on the same pixel.
  const off = (live.size * 28) % 200;
  return {
    x: Math.max(SIDE_MARGIN, Math.min(maxX, vw / 2 - w / 2 + off)),
    y: Math.max(TOP_MARGIN,  Math.min(maxY, vh / 2 - h / 2 + off)),
    w,
    h,
  };
}
