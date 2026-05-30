/**
 * Ambient world chrome. Minimal corner accents, soft scan beam, ghost grid.
 * Everything pointer-events-none. Purely atmospheric.
 */
export default function CornerFrame() {
  return (
    <div className="absolute inset-0 pointer-events-none z-30 overflow-hidden">
      {/* Whisper-thin corner accents */}
      <Corner position="tl" />
      <Corner position="tr" />
      <Corner position="bl" />
      <Corner position="br" />

      {/* Soft drifting scan beam */}
      <div className="absolute left-0 right-0 animate-scan">
        <div className="scanline" />
      </div>

      {/* Ghost grid — very faint depth cue */}
      <div className="absolute inset-0 bg-grid bg-grid opacity-[0.035]" />

      {/* Edge vignette — focus eye on center */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 55%, rgba(2,5,12,0.45) 100%)",
        }}
      />
    </div>
  );
}

function Corner({ position }: { position: "tl" | "tr" | "bl" | "br" }) {
  const map = {
    tl: "top-4 left-4 border-l border-t rounded-tl-lg",
    tr: "top-4 right-4 border-r border-t rounded-tr-lg",
    bl: "bottom-4 left-4 border-l border-b rounded-bl-lg",
    br: "bottom-4 right-4 border-r border-b rounded-br-lg",
  } as const;
  return (
    <div
      className={`absolute w-10 h-10 ${map[position]}`}
      style={{
        borderColor: "rgba(186,230,253,0.35)",
        boxShadow: "0 0 18px -4px rgba(125,211,252,0.35)",
      }}
    />
  );
}
