/**
 * MEDIA REVEAL v2 — "JARVIS Materialise".
 *
 * A six-stage holographic boot sequence per card. Universal base for every
 * card; kind-specific accents for image / 3D / web / page / model3d / galaxy.
 *
 * Stage timeline (ms):
 *   charge   0   → 180   Energy particles converge from outside the card.
 *   bloom    180 → 360   Centre dot → hairline → cyan rect, with an RGB
 *                        chromatic split flash and hex grid fade-in.
 *   settle   360 → 760   Content de-blurs + lifts. Lock-on brackets snap,
 *                        tactical chip pops, datastream finishes second
 *                        pass, hex grid fades out.
 *   breath   760 → 1500  Edge halo pulses gently then dies.
 *   done     1500+       All overlays unmounted.
 *
 * Plays once per card.id (memoised in module-level Set). Filter switches
 * and sorts never replay. All overlays are `pointer-events: none`.
 */
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { MediaKind } from "../../lib/store";

// Per-card playback memory. Persists across filter switches / re-sorts.
const REVEALED = new Set<string>();

type Phase = "charge" | "bloom" | "settle" | "breath" | "done";

const EASE = [0.16, 1, 0.3, 1] as const;

const ACCENT_KINDS: MediaKind[] = ["image", "images", "model3d"];
const RAIN_KINDS:   MediaKind[] = ["search", "news", "page", "pdf"];
const GRID_KINDS:   MediaKind[] = ["model3d", "galaxy"];

const KIND_READOUT: Record<MediaKind, string> = {
  search:  "◢ DATA DECRYPTED",
  news:    "◢ NEWSWIRE ONLINE",
  page:    "◢ DOCUMENT CACHED",
  pdf:     "◢ DOCUMENT CACHED",
  image:   "◢ TARGET LOCK",
  images:  "◢ TARGETS LOCKED",
  video:   "◢ SIGNAL ACQUIRED",
  videos:  "◢ SIGNALS ACQUIRED",
  webcam:  "◢ FEED ONLINE",
  galaxy:  "◢ NEURAL MAP",
  model3d: "◢ MODEL ASSEMBLED",
};

export default function MediaReveal({
  cardId,
  kind,
  children,
}: {
  cardId: string;
  kind: MediaKind;
  children: ReactNode;
}) {
  const initialDone = REVEALED.has(cardId);
  const [phase, setPhase] = useState<Phase>(initialDone ? "done" : "charge");

  useEffect(() => {
    if (initialDone) return;
    // NB: REVEALED is added only when the "done" phase actually fires.
    // React 18 StrictMode mounts→unmounts→remounts in dev; if we marked the
    // card as revealed at effect-mount time, the remount would short-circuit
    // straight to "done" and the user would never see the animation.
    const t1 = setTimeout(() => setPhase("bloom"),  180);
    const t2 = setTimeout(() => setPhase("settle"), 360);
    const t3 = setTimeout(() => setPhase("breath"), 760);
    const t4 = setTimeout(() => {
      setPhase("done");
      REVEALED.add(cardId);
    }, 1500);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); clearTimeout(t4); };
  }, [cardId, initialDone]);

  const isDone = phase === "done";

  return (
    <div className="relative" style={{ perspective: 900 }}>
      {/* Content — held back until bloom finishes, then de-blurs + lifts. */}
      <motion.div
        initial={isDone ? false : { opacity: 0, filter: "blur(10px)", rotateX: -7, y: 6 }}
        animate={
          isDone
            ? { opacity: 1, filter: "blur(0px)", rotateX: 0, y: 0 }
            : {
                opacity: phase === "charge" || phase === "bloom" ? 0 : 1,
                filter:  phase === "settle" || phase === "breath" ? "blur(0px)" : "blur(10px)",
                rotateX: phase === "charge" || phase === "bloom" ? -7 : 0,
                y:       phase === "charge" || phase === "bloom" ? 6  : 0,
              }
        }
        transition={{ duration: 0.46, ease: EASE, delay: phase === "settle" ? 0.04 : 0 }}
        style={{ transformOrigin: "50% 100%", transformStyle: "preserve-3d" }}
      >
        {children}
      </motion.div>

      <AnimatePresence>
        {!isDone && (
          <motion.div
            key="reveal-layers"
            className="pointer-events-none absolute inset-0 rounded-xl"
            initial={{ opacity: 1 }}
            exit={{ opacity: 0, transition: { duration: 0.3, ease: "easeOut" } }}
          >
            <div className="absolute inset-0 overflow-hidden rounded-xl">
              <EnergyCharge phase={phase} />
              <ChromaticBloom phase={phase} />
              {GRID_KINDS.includes(kind) && <HexField phase={phase} />}
              {!GRID_KINDS.includes(kind) && <HexField phase={phase} subtle />}
              {ACCENT_KINDS.includes(kind) && <ReticleRing phase={phase} />}
              {RAIN_KINDS.includes(kind)   && <Datastream    phase={phase} />}
              <EdgeBreath phase={phase} />
            </div>
            {/* Brackets sit ABOVE the clipped layer so they can punch past the
                card's rounded clip while flying in from outside. */}
            {ACCENT_KINDS.includes(kind) && <LockOnBrackets phase={phase} />}
            <TacticalChip phase={phase} label={KIND_READOUT[kind] ?? "◢ READY"} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ═════════════ Energy charge (0–180 ms) ═════════════
 *
 * Four cyan motes streak inward from outside the card edges along curved
 * paths, converging on the centre point where the bloom is about to ignite.
 */
function EnergyCharge({ phase }: { phase: Phase }) {
  const motes = useMemo(
    () => ([
      { from: { x: "-30%", y: "20%" } },
      { from: { x: "130%", y: "30%" } },
      { from: { x: "20%",  y: "-40%" } },
      { from: { x: "80%",  y: "140%" } },
      { from: { x: "-30%", y: "80%" } },
      { from: { x: "130%", y: "70%" } },
    ]),
    [],
  );
  if (phase !== "charge") return null;
  return (
    <div className="absolute inset-0">
      {motes.map((m, i) => (
        <motion.div
          key={i}
          className="absolute"
          style={{
            left: "50%", top: "50%",
            width: 4, height: 4, borderRadius: 9999,
            background: "rgba(186,230,253,0.95)",
            boxShadow: "0 0 14px 3px rgba(125,211,252,0.95), 0 0 4px 1px rgba(186,230,253,1)",
          }}
          initial={{ x: m.from.x, y: m.from.y, opacity: 0, scale: 0.6 }}
          animate={{
            x: "-50%", y: "-50%", opacity: [0, 1, 1, 0.2], scale: [0.6, 1, 1.4, 0.2],
          }}
          transition={{ duration: 0.22, ease: "easeIn", delay: i * 0.015 }}
        />
      ))}
    </div>
  );
}

/* ═════════════ Chromatic bloom (180–360 ms) ═════════════
 *
 * Iron-Man repulsor with an RGB-split twist: the central dot stretches into
 * a hairline, but at the bloom peak the white-cyan flash splits briefly
 * into red/green/blue offsets — same "channel-shear" feel as Tony's HUD
 * boot up.
 */
function ChromaticBloom({ phase }: { phase: Phase }) {
  const active = phase === "charge" || phase === "bloom" || phase === "settle";
  if (!active) return null;
  return (
    <div className="absolute inset-0 flex items-center justify-center">
      {/* Centre dot — present during charge + bloom */}
      <motion.div
        className="absolute"
        style={{
          width: 8, height: 8, borderRadius: 9999,
          background: "rgba(255,255,255,0.98)",
          boxShadow: "0 0 30px 8px rgba(125,211,252,0.95), 0 0 8px 2px #ffffff",
        }}
        initial={{ scale: 0, opacity: 0 }}
        animate={
          phase === "charge" ? { scale: [0, 1.1], opacity: [0, 1] } :
          phase === "bloom"  ? { scale: 1.6, opacity: 1 } :
          { scale: 0, opacity: 0 }
        }
        transition={{ duration: phase === "charge" ? 0.18 : 0.16, ease: "easeOut" }}
      />

      {/* RGB chromatic-split hairlines. Each channel is offset a few pixels
          horizontally — when they overlap on white you get a clean flash;
          when they're offset you get the classic Iron-Man HUD shear. */}
      <RGBHairline phase={phase} channel="r" offset={-3} />
      <RGBHairline phase={phase} channel="g" offset={0}  />
      <RGBHairline phase={phase} channel="b" offset={3}  />

      {/* Vertical rect expand — radial cyan haze that grows out from the
          hairline and dies as the content fades in. */}
      <motion.div
        className="absolute inset-x-0 mx-auto"
        style={{
          background:
            "radial-gradient(ellipse at center, rgba(125,211,252,0.55) 0%, rgba(125,211,252,0.15) 50%, rgba(14,24,42,0) 80%)",
          mixBlendMode: "screen",
        }}
        initial={{ height: 2, top: "50%", y: "-50%", opacity: 0 }}
        animate={
          phase === "charge" ? { height: 2, opacity: 0 } :
          phase === "bloom"  ? { height: 4, opacity: 0.95 } :
          { height: "100%", top: 0, y: 0, opacity: 0 }
        }
        transition={{
          height:  { duration: 0.36, ease: EASE },
          top:     { duration: 0.36, ease: EASE },
          y:       { duration: 0.36, ease: EASE },
          opacity: { duration: 0.6,  ease: "easeOut" },
        }}
      />

      {/* Inner halo flash. Fires once on the settle boundary. */}
      <motion.div
        className="absolute inset-0 rounded-xl"
        style={{
          boxShadow:
            "0 0 0 1px rgba(186,230,253,0.65) inset, 0 0 56px -4px rgba(125,211,252,0.75), 0 0 10px 0 rgba(186,230,253,0.55) inset",
        }}
        initial={{ opacity: 0 }}
        animate={phase === "settle" ? { opacity: [0, 1, 0] } : { opacity: 0 }}
        transition={{ duration: 0.5, ease: "easeOut", times: [0, 0.2, 1] }}
      />
    </div>
  );
}

function RGBHairline({
  phase, channel, offset,
}: {
  phase: Phase;
  channel: "r" | "g" | "b";
  offset: number;
}) {
  const color =
    channel === "r" ? "rgba(255,90,90,0.95)" :
    channel === "g" ? "rgba(120,255,180,0.95)" :
                      "rgba(125,211,252,0.95)";
  const visible = phase === "bloom" || phase === "settle";
  return (
    <motion.div
      className="absolute left-0 right-0 mx-auto"
      style={{
        height: 2,
        x: offset,
        background: `linear-gradient(90deg, transparent 0%, ${color} 50%, transparent 100%)`,
        mixBlendMode: "screen",
        filter: "blur(0.4px)",
      }}
      initial={{ scaleX: 0, opacity: 0 }}
      animate={
        phase === "bloom"  ? { scaleX: 1, opacity: 1, x: offset } :
        phase === "settle" ? { scaleX: 1, opacity: 0, x: offset * 4 } :
        { scaleX: 0, opacity: 0 }
      }
      transition={{
        scaleX:  { duration: 0.24, ease: EASE },
        opacity: { duration: 0.36, ease: "easeOut" },
        x:       { duration: 0.36, ease: "easeOut" },
      }}
    />
  );
}

/* ═════════════ Hex grid field (background, phase-tinted) ═════════════
 *
 * SVG pattern of cyan hex outlines. Tints in at bloom peak, drifts upward
 * during settle, then fades. `subtle` mode used as the universal backdrop
 * for non-3D cards; full mode for galaxy / model3d (denser + slower fade).
 */
function HexField({ phase, subtle = false }: { phase: Phase; subtle?: boolean }) {
  const visible = phase === "bloom" || phase === "settle";
  if (!visible && phase !== "breath") return null;

  const targetOpacity =
    phase === "bloom"  ? (subtle ? 0.25 : 0.55) :
    phase === "settle" ? (subtle ? 0.18 : 0.45) :
    0;

  return (
    <motion.svg
      className="absolute inset-0 w-full h-full"
      initial={{ opacity: 0 }}
      animate={{ opacity: targetOpacity, y: phase === "settle" ? -8 : 0 }}
      transition={{ opacity: { duration: 0.4 }, y: { duration: 0.7, ease: "easeOut" } }}
      preserveAspectRatio="none"
      style={{ mixBlendMode: "screen" }}
    >
      <defs>
        <pattern id={`hex-${subtle ? "s" : "f"}`} width="22" height="38" patternUnits="userSpaceOnUse" patternTransform="scale(1)">
          <path
            d="M11 0 L22 6.35 V19.05 L11 25.4 L0 19.05 V6.35 Z"
            fill="none"
            stroke="rgba(125,211,252,0.85)"
            strokeWidth={subtle ? 0.6 : 0.9}
          />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#hex-${subtle ? "s" : "f"})`} />
    </motion.svg>
  );
}

/* ═════════════ HUD Lock-On Brackets (image / model3d) ═════════════
 *
 * Four cyan reticle corners fly in from outside the card, snap to its
 * corners with a faint overshoot, then shrink to small accent ticks. Sits
 * outside the clipped overlay so the fly-in path crosses the card edge
 * cleanly.
 */
function LockOnBrackets({ phase }: { phase: Phase }) {
  const corners: { side: "tl" | "tr" | "bl" | "br"; from: { x: number; y: number } }[] = [
    { side: "tl", from: { x: -22, y: -22 } },
    { side: "tr", from: { x:  22, y: -22 } },
    { side: "bl", from: { x: -22, y:  22 } },
    { side: "br", from: { x:  22, y:  22 } },
  ];
  return (
    <>
      {corners.map((c) => (
        <Bracket key={c.side} side={c.side} from={c.from} phase={phase} />
      ))}
    </>
  );
}

function Bracket({
  side, from, phase,
}: {
  side: "tl" | "tr" | "bl" | "br";
  from: { x: number; y: number };
  phase: Phase;
}) {
  const isLeft = side === "tl" || side === "bl";
  const isTop  = side === "tl" || side === "tr";
  const pos: React.CSSProperties = {
    top:    isTop  ? 6  : "auto",
    bottom: !isTop ? 6  : "auto",
    left:   isLeft ? 6  : "auto",
    right:  !isLeft ? 6 : "auto",
  };

  const long = 20;
  const short = 2;

  const wide =
    phase === "settle" ? 12 :
    phase === "breath" ? 8  :
    long;

  return (
    <motion.div
      className="absolute"
      style={{ width: long, height: long, ...pos }}
      initial={{ x: from.x, y: from.y, opacity: 0, scale: 1.2, rotate: 8 }}
      animate={
        phase === "charge"
          ? { x: from.x, y: from.y, opacity: 0, scale: 1.2, rotate: 8 }
          : phase === "bloom"
          ? { x: from.x * 0.45, y: from.y * 0.45, opacity: 0.95, scale: 1.1, rotate: 4 }
          : phase === "settle"
          ? { x: 0, y: 0, opacity: 1, scale: 1, rotate: 0 }
          : { x: 0, y: 0, opacity: 0.55, scale: 1, rotate: 0 }
      }
      transition={{ duration: 0.38, ease: EASE }}
    >
      <motion.div
        className="absolute"
        style={{
          top: isTop ? 0 : "auto",
          bottom: !isTop ? 0 : "auto",
          left: isLeft ? 0 : "auto",
          right: !isLeft ? 0 : "auto",
          height: short,
          background: "linear-gradient(90deg, rgba(186,230,253,1), rgba(125,211,252,0.65))",
          boxShadow: "0 0 10px 1px rgba(125,211,252,0.85)",
        }}
        initial={{ width: long }}
        animate={{ width: wide }}
        transition={{ duration: 0.32, ease: EASE, delay: phase === "settle" ? 0.3 : 0 }}
      />
      <motion.div
        className="absolute"
        style={{
          top: isTop ? 0 : "auto",
          bottom: !isTop ? 0 : "auto",
          left: isLeft ? 0 : "auto",
          right: !isLeft ? 0 : "auto",
          width: short,
          background: "linear-gradient(180deg, rgba(186,230,253,1), rgba(125,211,252,0.65))",
          boxShadow: "0 0 10px 1px rgba(125,211,252,0.85)",
        }}
        initial={{ height: long }}
        animate={{ height: wide }}
        transition={{ duration: 0.32, ease: EASE, delay: phase === "settle" ? 0.3 : 0 }}
      />
    </motion.div>
  );
}

/* ═════════════ Reticle ring (image / model3d) ═════════════
 *
 * Brief crosshair ring spins up at the centre during bloom→settle handover.
 * Sells the "TARGET LOCK" beat before the chip text appears.
 */
function ReticleRing({ phase }: { phase: Phase }) {
  if (phase === "done" || phase === "charge" || phase === "breath") return null;
  return (
    <motion.svg
      viewBox="0 0 100 100"
      className="absolute"
      style={{
        left: "50%", top: "50%", width: 48, height: 48,
        transform: "translate(-50%,-50%)",
        mixBlendMode: "screen",
      }}
      initial={{ opacity: 0, scale: 0.4, rotate: -30 }}
      animate={
        phase === "bloom"  ? { opacity: 0.9, scale: 1,   rotate: 90 } :
        phase === "settle" ? { opacity: 0,   scale: 1.3, rotate: 180 } :
        { opacity: 0, scale: 0.4, rotate: -30 }
      }
      transition={{ duration: 0.55, ease: EASE }}
    >
      <circle cx="50" cy="50" r="34" fill="none"
              stroke="rgba(186,230,253,0.9)" strokeWidth="0.8"
              strokeDasharray="4 6" />
      <circle cx="50" cy="50" r="22" fill="none"
              stroke="rgba(125,211,252,0.95)" strokeWidth="0.6" />
      <line x1="50" y1="6"  x2="50" y2="18" stroke="rgba(186,230,253,1)" strokeWidth="1" />
      <line x1="50" y1="82" x2="50" y2="94" stroke="rgba(186,230,253,1)" strokeWidth="1" />
      <line x1="6"  y1="50" x2="18" y2="50" stroke="rgba(186,230,253,1)" strokeWidth="1" />
      <line x1="82" y1="50" x2="94" y2="50" stroke="rgba(186,230,253,1)" strokeWidth="1" />
    </motion.svg>
  );
}

/* ═════════════ Datastream rain — two-pass (search / page / pdf) ═════════════
 *
 * Down-pass scatters monospace cyan glyphs through the card while bloom
 * resolves; up-pass sends a brighter "seal" wave back through during
 * settle. Reads as "fetch → decode → confirmed". Pure DOM, ~30 spans peak.
 */
const RAIN_GLYPHS = "01░▒▓<>{}=*+-?λΣΩΔ#@&$";

function Datastream({ phase }: { phase: Phase }) {
  const stripes = useMemo(() => {
    const n = 7;
    return Array.from({ length: n }, (_, i) => ({
      left:  `${(i + 0.5) * (100 / n) + (Math.random() - 0.5) * 5}%`,
      delay: Math.random() * 0.1,
      chars: Array.from({ length: 5 }, () => RAIN_GLYPHS[Math.floor(Math.random() * RAIN_GLYPHS.length)]),
    }));
  }, []);

  if (phase === "charge" || phase === "breath" || phase === "done") return null;

  return (
    <div className="absolute inset-0 overflow-hidden">
      {stripes.map((s, i) => (
        <Stripe key={i} left={s.left} delay={s.delay} chars={s.chars} phase={phase} />
      ))}
      {/* Bottom scanline — confirms the decode pass. */}
      <motion.div
        className="absolute inset-x-0 h-px"
        style={{
          background: "linear-gradient(90deg, transparent, rgba(186,230,253,0.95), transparent)",
          boxShadow: "0 0 12px rgba(125,211,252,0.85)",
        }}
        initial={{ top: 0, opacity: 0 }}
        animate={
          phase === "bloom"  ? { top: "50%", opacity: 0.95 } :
          phase === "settle" ? { top: "100%", opacity: 0 } :
          { top: 0, opacity: 0 }
        }
        transition={{ duration: 0.5, ease: "easeOut" }}
      />
      {/* Up-pass "seal" line. Slightly delayed; fades on completion. */}
      <motion.div
        className="absolute inset-x-0 h-px"
        style={{
          background: "linear-gradient(90deg, transparent, rgba(186,230,253,0.7), transparent)",
          boxShadow: "0 0 8px rgba(125,211,252,0.55)",
        }}
        initial={{ top: "100%", opacity: 0 }}
        animate={phase === "settle" ? { top: "0%", opacity: [0, 0.8, 0] } : { top: "100%", opacity: 0 }}
        transition={{ duration: 0.5, ease: "easeOut", times: [0, 0.4, 1] }}
      />
    </div>
  );
}

function Stripe({
  left, delay, chars, phase,
}: {
  left: string;
  delay: number;
  chars: string[];
  phase: Phase;
}) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (phase === "done" || phase === "charge" || phase === "breath") return;
    const id = window.setInterval(() => setTick((t) => t + 1), 95);
    return () => window.clearInterval(id);
  }, [phase]);

  const glyphs = useMemo(
    () => chars.map(() => RAIN_GLYPHS[Math.floor(Math.random() * RAIN_GLYPHS.length)]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tick],
  );

  return (
    <motion.div
      className="absolute -top-8 flex flex-col items-center text-mono"
      style={{ left, transform: "translateX(-50%)" }}
      initial={{ y: "-40%", opacity: 0 }}
      animate={
        phase === "bloom"  ? { y: "20%",  opacity: 1 } :
        phase === "settle" ? { y: "120%", opacity: 0 } :
        { y: "-40%", opacity: 0 }
      }
      transition={{ duration: 0.6, ease: "easeIn", delay }}
    >
      {glyphs.map((g, i) => (
        <span
          key={i}
          className="leading-[1] text-[11px]"
          style={{
            color: i === 0
              ? "rgba(186,230,253,1)"
              : `rgba(125,211,252,${0.9 - i * 0.16})`,
            textShadow: "0 0 8px rgba(125,211,252,0.95)",
          }}
        >
          {g}
        </span>
      ))}
    </motion.div>
  );
}

/* ═════════════ Tactical readout chip ═════════════
 *
 * Per-kind text snap: ◢ TARGET LOCK, ◢ DATA DECRYPTED, etc. Pops in at the
 * settle boundary with a tiny char-decode shimmer, holds briefly, fades.
 */
function TacticalChip({ phase, label }: { phase: Phase; label: string }) {
  const visible = phase === "settle" || phase === "breath";

  // Char-decode: replace each char with a random glyph for a few frames,
  // then settle to the real char.
  const [out, setOut] = useState(label);
  useEffect(() => {
    if (!visible) { setOut(label); return; }
    let frame = 0;
    const id = window.setInterval(() => {
      frame++;
      if (frame > 6) { setOut(label); window.clearInterval(id); return; }
      const scrambled = label
        .split("")
        .map((ch, i) => (frame * 2 > i || ch === " " || ch === "◢")
          ? ch
          : RAIN_GLYPHS[Math.floor(Math.random() * RAIN_GLYPHS.length)])
        .join("");
      setOut(scrambled);
    }, 35);
    return () => window.clearInterval(id);
  }, [visible, label]);

  return (
    <motion.div
      className="absolute top-2 right-2 px-2 py-[3px] rounded-md text-mono tabular-nums"
      style={{
        fontSize: 9,
        letterSpacing: "0.18em",
        color: "rgba(186,230,253,0.95)",
        background: "rgba(14,24,42,0.55)",
        border: "1px solid rgba(125,211,252,0.55)",
        boxShadow: "0 0 18px -4px rgba(125,211,252,0.65), 0 0 0 1px rgba(186,230,253,0.1) inset",
        backdropFilter: "blur(6px)",
      }}
      initial={{ opacity: 0, x: 8, scale: 0.9 }}
      animate={
        phase === "settle" ? { opacity: 1,   x: 0, scale: 1 } :
        phase === "breath" ? { opacity: 0.7, x: 0, scale: 1 } :
        { opacity: 0, x: 8, scale: 0.9 }
      }
      transition={{ duration: 0.3, ease: EASE }}
    >
      {out}
    </motion.div>
  );
}

/* ═════════════ Edge breath (760–1500 ms) ═════════════
 *
 * Soft cyan border glow that pulses once and decays. Sits on top of the
 * settled card without blocking interaction.
 */
function EdgeBreath({ phase }: { phase: Phase }) {
  if (phase !== "settle" && phase !== "breath") return null;
  return (
    <motion.div
      className="absolute inset-0 rounded-xl"
      style={{
        boxShadow: "0 0 0 1px rgba(125,211,252,0.45) inset, 0 0 28px -4px rgba(125,211,252,0.55)",
      }}
      initial={{ opacity: 0 }}
      animate={
        phase === "settle" ? { opacity: [0, 0.95, 0.6] } :
        phase === "breath" ? { opacity: [0.6, 0.85, 0] } :
        { opacity: 0 }
      }
      transition={{ duration: phase === "settle" ? 0.4 : 0.74, ease: "easeOut", times: [0, 0.35, 1] }}
    />
  );
}
