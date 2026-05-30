/**
 * Full-screen drag-drop overlay. Catches files dropped anywhere on the
 * window, converts images to data URLs, attaches to next chat message.
 * Other files POST to /api/upload and attach by URL.
 *
 * Once images are attached, the CommandBar's ImageActions bar surfaces
 * one-click ANALYZE / IMG2IMG / TO 3D workflows.
 */
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { useStore, type ChatAttachment } from "../../lib/store";

const MAX_IMAGE_BYTES = 8 * 1024 * 1024; // 8 MB inline cap

export default function DropZone() {
  const [active, setActive] = useState(false);
  const addAttachment = useStore((s) => s.addAttachment);

  useEffect(() => {
    let depth = 0;

    const onEnter = (e: DragEvent) => {
      if (!e.dataTransfer?.types.includes("Files")) return;
      depth++;
      setActive(true);
      e.preventDefault();
    };
    const onOver = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("Files")) {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
      }
    };
    const onLeave = (e: DragEvent) => {
      if (!e.dataTransfer?.types.includes("Files")) return;
      depth--;
      if (depth <= 0) {
        depth = 0;
        setActive(false);
      }
    };
    const onDrop = async (e: DragEvent) => {
      e.preventDefault();
      depth = 0;
      setActive(false);
      const files = Array.from(e.dataTransfer?.files || []);
      for (const f of files) {
        await handleFile(f, addAttachment);
      }
    };

    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragover", onOver);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [addAttachment]);

  return (
    <AnimatePresence>
      {active && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[300] pointer-events-none flex items-center justify-center bg-jarvis-ink/70 backdrop-blur-sm"
        >
          <div className="holo-panel p-8 text-center relative">
            <div className="text-display text-jarvis-aqua text-2xl tracking-widest glow-text mb-3">
              DROP TO ATTACH
            </div>
            <div className="text-mono text-xs text-jarvis-cyan/70 space-y-1">
              <div>images attach inline for vision analysis</div>
              <div className="flex items-center justify-center gap-3 mt-2 text-[10px]">
                <span className="text-emerald-400 border border-emerald-400/40 px-1.5 py-0.5">🔍 ANALYZE</span>
                <span className="text-violet-400 border border-violet-400/40 px-1.5 py-0.5">🎨 IMG2IMG</span>
                <span className="text-amber-400 border border-amber-400/40 px-1.5 py-0.5">🧊 TO 3D</span>
              </div>
            </div>
            <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-jarvis-aqua" />
            <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-jarvis-aqua" />
            <div className="absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 border-jarvis-aqua" />
            <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-jarvis-aqua" />
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

async function handleFile(f: File, add: (a: ChatAttachment) => void) {
  const isImage = f.type.startsWith("image/");
  if (isImage && f.size <= MAX_IMAGE_BYTES) {
    // Inline base64 — direct to model as multimodal attachment.
    const dataUrl = await fileToDataURL(f);
    add({
      type: "image",
      name: f.name,
      data_url: dataUrl,
      size: f.size,
      mime: f.type,
    });
    return;
  }
  // Non-image OR too big → upload to backend, attach URL.
  const form = new FormData();
  form.append("file", f);
  try {
    const resp = await fetch("/api/upload", { method: "POST", body: form });
    const data = await resp.json();
    if (data?.url) {
      add({
        type: isImage ? "image" : "file",
        name: f.name,
        url: data.url,
        data_url: data.data_url || undefined,
        size: f.size,
        mime: f.type,
      });
    }
  } catch (e) {
    console.error("upload failed", e);
  }
}

function fileToDataURL(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(f);
  });
}
