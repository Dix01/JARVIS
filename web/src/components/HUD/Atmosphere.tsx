/**
 * AMBIENT WORLD LAYER — sits behind everything.
 *  · cursor-tracked aurora light (huge soft radial follows mouse, lerp)
 *  · 3 drifting mesh blobs (cyan / violet / teal) — pure CSS animation
 *  · SVG turbulence film grain (high-quality, not background-image)
 *  · soft top + bottom edge fades
 *
 * Pure presentation, pointer-events: none. ~0 JS cost per frame after raf.
 */
export default function Atmosphere() {
  return (
    <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
      {/* Drifting mesh blobs */}
      <div className="atm-blob atm-blob-1" />
      <div className="atm-blob atm-blob-2" />
      <div className="atm-blob atm-blob-3" />

      {/* Soft edge falloff — frames the scene */}
      <div className="absolute inset-0" style={{
        background:
          "radial-gradient(ellipse 90% 100% at 50% 50%, transparent 50%, rgba(2,5,12,0.55) 100%)",
      }} />

    </div>
  );
}
