/**
 * ImageActions — smart action bar displayed on pending image attachments.
 *
 * When one or more images are staged in the CommandBar, this bar offers
 * three one-click workflows:
 *   🔍 ANALYZE  — send the image to the LLM for vision description
 *   🎨 IMG2IMG  — open a prompt input and generate a new image from it
 *   🧊 TO 3D   — convert the image to a GLB 3D model
 *
 * Each action posts directly to the dedicated REST endpoint and pushes
 * results into the chat + media bay via WebSocket or store updates.
 */
import { useState, useRef } from "react";
import { useStore, nextId, type ChatAttachment, type MediaKind } from "../../lib/store";
import { analyzeImage, img2img, imageTo3D } from "../../lib/api";

interface ImageActionsProps {
  /** The pending image attachments (should contain at least one image). */
  images: ChatAttachment[];
}

const MEDIA_PREFIX = "__JARVIS_MEDIA__";

function pushReturnedMedia(result: string, tool: string, query?: string): string | null {
  if (!result.startsWith(MEDIA_PREFIX)) return null;
  try {
    const payload = JSON.parse(result.slice(MEDIA_PREFIX.length));
    const kind = (payload.kind || "image") as MediaKind;
    useStore.getState().pushMedia({
      id: nextId(),
      kind,
      items: Array.isArray(payload.items) ? payload.items : [],
      summary: payload.summary || "",
      tool,
      query,
      ts: Date.now(),
      expanded: kind === "page" ? 0 : null,
      ...(kind === "galaxy" ? { galaxy: { nodes: payload.items || [], clusters: payload.clusters || [] } } : {}),
    });
    return payload.summary || "Result added to Media Bay";
  } catch {
    return null;
  }
}

/**
 * Reconstruct a File from a ChatAttachment. If the attachment has a data_url,
 * we decode it to a Blob → File. If it has a plain url, we fetch it first.
 */
async function attachmentToFile(att: ChatAttachment): Promise<File> {
  if (att.data_url) {
    const res = await fetch(att.data_url);
    const blob = await res.blob();
    return new File([blob], att.name || "image.png", { type: att.mime || "image/png" });
  }
  if (att.url) {
    const res = await fetch(att.url);
    const blob = await res.blob();
    return new File([blob], att.name || "image.png", { type: att.mime || "image/png" });
  }
  throw new Error("attachment has no data");
}

export default function ImageActions({ images }: ImageActionsProps) {
  const pushChat = useStore((s) => s.pushChat);
  const clearAttachments = useStore((s) => s.clearAttachments);
  const setOrb = useStore((s) => s.setOrb);

  const [busy, setBusy] = useState<string | null>(null); // "analyze" | "img2img" | "3d" | null
  const [showPrompt, setShowPrompt] = useState(false);
  const [promptVal, setPromptVal] = useState("");
  const promptRef = useRef<HTMLInputElement>(null);

  if (images.length === 0) return null;

  const firstImage = images[0];

  // ── ANALYZE ───────────────────────────────────────────────────────────
  const doAnalyze = async () => {
    setBusy("analyze");
    setOrb("thinking");
    pushChat({
      id: nextId(),
      role: "user",
      text: "Analyze this image",
      ts: Date.now(),
      attachments: [...images],
    });
    try {
      const file = await attachmentToFile(firstImage);
      const resp = await analyzeImage(file);
      if (resp.ok && resp.analysis) {
        pushChat({
          id: nextId(),
          role: "assistant",
          text: resp.analysis,
          ts: Date.now(),
        });
      } else {
        pushChat({
          id: nextId(),
          role: "error",
          text: resp.error || "Analysis failed",
          ts: Date.now(),
        });
      }
    } catch (e: any) {
      pushChat({
        id: nextId(),
        role: "error",
        text: `Analysis error: ${e.message}`,
        ts: Date.now(),
      });
    } finally {
      setBusy(null);
      setOrb("idle");
      clearAttachments();
    }
  };

  // ── IMG2IMG ───────────────────────────────────────────────────────────
  const doImg2Img = async () => {
    if (!showPrompt) {
      setShowPrompt(true);
      requestAnimationFrame(() => promptRef.current?.focus());
      return;
    }
    const prompt = promptVal.trim() || "transform this image creatively";
    setBusy("img2img");
    setOrb("thinking");
    pushChat({
      id: nextId(),
      role: "user",
      text: `img2img: ${prompt}`,
      ts: Date.now(),
      attachments: [...images],
    });
    setShowPrompt(false);
    try {
      const file = await attachmentToFile(firstImage);
      const resp = await img2img(file, prompt);
      if (resp.ok && resp.result) {
        // REST image actions bypass the WebSocket dispatcher, so push the
        // returned media payload into the bay directly.
        const summary = pushReturnedMedia(resp.result, "image_generate", prompt);
        pushChat({
          id: nextId(),
          role: summary ? "assistant" : "error",
          text: summary || resp.result,
          ts: Date.now(),
        });
      } else {
        pushChat({
          id: nextId(),
          role: "error",
          text: resp.error || "img2img failed",
          ts: Date.now(),
        });
      }
    } catch (e: any) {
      pushChat({
        id: nextId(),
        role: "error",
        text: `img2img error: ${e.message}`,
        ts: Date.now(),
      });
    } finally {
      setBusy(null);
      setOrb("idle");
      clearAttachments();
      setPromptVal("");
    }
  };

  // ── TO 3D ─────────────────────────────────────────────────────────────
  const doTo3D = async () => {
    setBusy("3d");
    setOrb("thinking");
    pushChat({
      id: nextId(),
      role: "user",
      text: "Convert image to 3D model",
      ts: Date.now(),
      attachments: [...images],
    });
    try {
      const file = await attachmentToFile(firstImage);
      const resp = await imageTo3D(file);
      if (resp.ok && resp.result) {
        // REST image actions bypass the WebSocket dispatcher, so push the
        // returned media payload into the bay directly.
        const summary = pushReturnedMedia(resp.result, "image_to_3d", firstImage.name);
        pushChat({
          id: nextId(),
          role: summary ? "assistant" : "error",
          text: summary || resp.result,
          ts: Date.now(),
        });
      } else {
        pushChat({
          id: nextId(),
          role: "error",
          text: resp.error || "3D conversion failed",
          ts: Date.now(),
        });
      }
    } catch (e: any) {
      pushChat({
        id: nextId(),
        role: "error",
        text: `3D error: ${e.message}`,
        ts: Date.now(),
      });
    } finally {
      setBusy(null);
      setOrb("idle");
      clearAttachments();
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      {/* Action buttons row */}
      <div className="flex items-center gap-1.5">
        <ActionBtn
          icon={<AnalyzeIcon />}
          label="ANALYZE"
          sublabel="vision"
          onClick={doAnalyze}
          busy={busy === "analyze"}
          disabled={busy !== null && busy !== "analyze"}
          accentClass="text-emerald-400 border-emerald-400/50 hover:bg-emerald-400/10 hover:border-emerald-400"
        />
        <ActionBtn
          icon={<PaletteIcon />}
          label="IMG2IMG"
          sublabel="generate"
          onClick={doImg2Img}
          busy={busy === "img2img"}
          disabled={busy !== null && busy !== "img2img"}
          accentClass="text-violet-400 border-violet-400/50 hover:bg-violet-400/10 hover:border-violet-400"
        />
        <ActionBtn
          icon={<CubeIcon />}
          label="TO 3D"
          sublabel="mesh"
          onClick={doTo3D}
          busy={busy === "3d"}
          disabled={busy !== null && busy !== "3d"}
          accentClass="text-amber-400 border-amber-400/50 hover:bg-amber-400/10 hover:border-amber-400"
        />
      </div>
      {/* img2img prompt input */}
      {showPrompt && (
        <div className="flex items-center gap-1.5 animate-boot_in">
          <span className="text-mono text-[10px] text-violet-400/60">prompt ›</span>
          <input
            ref={promptRef}
            value={promptVal}
            onChange={(e) => setPromptVal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                doImg2Img();
              }
              if (e.key === "Escape") setShowPrompt(false);
            }}
            placeholder="describe transformation…"
            className="flex-1 bg-transparent border border-violet-400/40 focus:border-violet-400 rounded-lg outline-none px-2.5 py-1 text-violet-300 text-mono text-xs placeholder:text-violet-400/30 transition-colors"
          />
          <button
            onClick={doImg2Img}
            disabled={busy !== null}
            className="px-2.5 py-1 rounded-lg border border-violet-400/50 text-violet-400 hover:bg-violet-400/10 text-mono text-[10px] uppercase tracking-wider disabled:opacity-30 transition-colors"
          >
            go
          </button>
        </div>
      )}
    </div>
  );
}

function ActionBtn({
  icon,
  label,
  sublabel,
  onClick,
  busy,
  disabled,
  accentClass,
}: {
  icon: React.ReactNode;
  label: string;
  sublabel: string;
  onClick: () => void;
  busy: boolean;
  disabled: boolean;
  accentClass: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-mono text-[10px] uppercase tracking-wider transition-all disabled:opacity-30 ${accentClass} ${
        busy ? "animate-pulse" : ""
      }`}
      title={`${label}: ${sublabel}`}
    >
      {busy ? <Spinner /> : icon}
      <span>{label}</span>
    </button>
  );
}

function Spinner() {
  return (
    <svg className="animate-spin w-3.5 h-3.5" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" strokeDasharray="28" strokeDashoffset="8" />
    </svg>
  );
}

function AnalyzeIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="8" />
      <path d="M21 21l-4.35-4.35" />
      <path d="M11 8v6M8 11h6" />
    </svg>
  );
}

function PaletteIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function CubeIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" />
      <path d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12" />
    </svg>
  );
}
