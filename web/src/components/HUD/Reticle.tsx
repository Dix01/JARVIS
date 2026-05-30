/**
 * TARGETING RETICLE — follows the cursor with corner brackets.
 * Locks onto interactive elements (buttons / inputs) — "artificial foveation".
 *
 * Position is written directly to style.transform on every mousemove (zero
 * lag — no rAF lerp). Width/height morph is CSS-transitioned for a smooth
 * lock-on. setLocked/setLabel only fire on actual state change (no per-frame
 * React re-renders).
 */
import { useEffect, useRef, useState } from "react";

export default function Reticle() {
  const ref = useRef<HTMLDivElement>(null);
  const [locked, setLocked] = useState(false);
  const [label, setLabel] = useState<string>("");
  const lockedRef = useRef(false);
  const labelRef = useRef("");

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!ref.current) return;

      const el = document.elementFromPoint(e.clientX, e.clientY);
      const lockable = el?.closest("button, a, input, textarea, [data-reticle]");

      if (lockable) {
        const r = (lockable as HTMLElement).getBoundingClientRect();
        const w = r.width + 14;
        const h = r.height + 14;
        const x = r.left + r.width / 2 - w / 2;
        const y = r.top + r.height / 2 - h / 2;
        // Direct write — compositor handles the CSS size transition
        ref.current.style.transform = `translate(${x}px, ${y}px)`;
        ref.current.style.width = `${w}px`;
        ref.current.style.height = `${h}px`;

        if (!lockedRef.current) {
          lockedRef.current = true;
          setLocked(true);
        }
        const lbl = (
          (lockable as HTMLElement).getAttribute("aria-label") ||
          (lockable as HTMLElement).getAttribute("title") ||
          (lockable.textContent || "")
        ).trim().slice(0, 24);
        if (lbl !== labelRef.current) {
          labelRef.current = lbl;
          setLabel(lbl);
        }
      } else {
        // Free-roam: instant position, reset size
        ref.current.style.transform = `translate(${e.clientX - 14}px, ${e.clientY - 14}px)`;
        ref.current.style.width = "28px";
        ref.current.style.height = "28px";

        if (lockedRef.current) {
          lockedRef.current = false;
          setLocked(false);
        }
        if (labelRef.current) {
          labelRef.current = "";
          setLabel("");
        }
      }
    };

    window.addEventListener("mousemove", onMove, { passive: true });
    return () => window.removeEventListener("mousemove", onMove);
  }, []);

  const color = locked ? "border-jarvis-aqua/90" : "border-jarvis-cyan/40";

  return (
    <div
      ref={ref}
      className="fixed top-0 left-0 z-[100] pointer-events-none"
      style={{
        width: 28,
        height: 28,
        transition: "width 110ms ease-out, height 110ms ease-out",
        filter: locked
          ? "drop-shadow(0 0 8px rgba(165,243,252,0.55))"
          : "drop-shadow(0 0 6px rgba(125,211,252,0.35))",
      }}
    >
      {/* Corner ticks */}
      <div className={`absolute top-0 left-0 w-2.5 h-2.5 border-t border-l rounded-tl-md ${color} transition-[border-color] duration-200`} />
      <div className={`absolute top-0 right-0 w-2.5 h-2.5 border-t border-r rounded-tr-md ${color} transition-[border-color] duration-200`} />
      <div className={`absolute bottom-0 left-0 w-2.5 h-2.5 border-b border-l rounded-bl-md ${color} transition-[border-color] duration-200`} />
      <div className={`absolute bottom-0 right-0 w-2.5 h-2.5 border-b border-r rounded-br-md ${color} transition-[border-color] duration-200`} />
      {/* Center dot */}
      <div className={`absolute inset-1/2 -translate-x-1/2 -translate-y-1/2 w-1 h-1 rounded-full ${locked ? "bg-jarvis-aqua shadow-[0_0_6px_rgba(165,243,252,0.9)]" : "bg-jarvis-cyan/70"}`} />
      {/* Label */}
      {locked && label && (
        <div className="absolute -top-5 left-full ml-2 whitespace-nowrap glass-chip text-jarvis-aqua border-jarvis-aqua/30">
          {label.toUpperCase()}
        </div>
      )}
    </div>
  );
}
