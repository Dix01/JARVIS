"""OPTIONAL: Vision — screenshots, OCR, webcam.

Disabled by default. Enable in config.yaml.
Install optional deps first:
    pip install mss pytesseract opencv-python Pillow
Also install tesseract.exe for OCR (https://github.com/UB-Mannheim/tesseract/wiki).

User consent is required: every capture is logged via the action log and
requires CAUTION (screenshot) or DANGEROUS (webcam) confirmation.
"""
from __future__ import annotations

import time
from pathlib import Path

from ..core.permissions import Permission
from .base import PluginInfo, tool


def register(registry):
    cfg = registry.cfg
    snap_dir = cfg.abs_path("data/screenshots")
    snap_dir.mkdir(parents=True, exist_ok=True)

    try:
        import mss  # noqa: F401
        _mss_ok = True
    except ImportError:
        _mss_ok = False

    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
        _ocr_ok = True
    except ImportError:
        _ocr_ok = False

    try:
        import cv2  # noqa: F401
        _cv_ok = True
    except ImportError:
        _cv_ok = False

    @tool(
        name="screenshot",
        description="Capture the primary screen and save a PNG. Requires user confirmation (no silent capture).",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {"label": {"type": "string", "default": ""}},
        },
        preview=lambda a: f"capture screen -> {a.get('label','') or 'screenshot'}.png",
    )
    def screenshot(label: str = "") -> str:
        if not _mss_ok:
            return "mss not installed (pip install mss)"
        import mss
        ts = time.strftime("%Y%m%d-%H%M%S")
        name = f"{label or 'screenshot'}-{ts}.png"
        path: Path = snap_dir / name
        with mss.mss() as sct:
            sct.shot(output=str(path), mon=-1)
        return f"saved {path}"

    @tool(
        name="ocr_image",
        description="Run OCR on an image file and return extracted text. Requires tesseract.",
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    def ocr_image(path: str) -> str:
        if not _ocr_ok:
            return "pytesseract / Pillow not installed"
        import os, pytesseract
        from PIL import Image
        from ..utils.files import expand
        # Auto-locate tesseract.exe on Windows if it isn't on PATH.
        if os.name == "nt" and not pytesseract.pytesseract.tesseract_cmd:
            for cand in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                         r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
                if os.path.isfile(cand):
                    pytesseract.pytesseract.tesseract_cmd = cand
                    break
        p = expand(path)
        if not p.exists():
            return f"not found: {p}"
        try:
            return pytesseract.image_to_string(Image.open(p))
        except pytesseract.TesseractNotFoundError:
            return ("tesseract binary not found on PATH. Install: "
                    "winget install UB-Mannheim.TesseractOCR  "
                    "(default path: C:\\Program Files\\Tesseract-OCR\\)")

    @tool(
        name="screen_ocr",
        description="Take a screenshot and OCR it in one step. Returns text.",
        permission=Permission.CAUTION,
        parameters={"type": "object", "properties": {}},
        preview=lambda a: "screenshot + OCR",
    )
    def screen_ocr() -> str:
        out = screenshot("ocr")
        if out.startswith("saved "):
            return ocr_image(out[6:])
        return out

    @tool(
        name="webcam_status",
        description="Detect whether a webcam is present.",
        permission=Permission.SAFE,
        parameters={"type": "object", "properties": {}},
    )
    def webcam_status() -> str:
        if not _cv_ok:
            return "opencv-python not installed"
        import cv2
        for idx in range(3):
            cap = cv2.VideoCapture(idx)
            ok = cap.isOpened()
            cap.release()
            if ok:
                return f"webcam available at index {idx}"
        return "no webcam detected"

    @tool(
        name="webcam_snapshot",
        description=(
            "BACKGROUND CAPTURE ONLY — saves a single webcam frame to disk and "
            "surfaces it in the Media Bay as an image card. Does NOT open a live "
            "viewer. For 'look at me / show me on camera / open webcam' the "
            "correct tool is `webcam_show`, which opens the LIVE feed inline."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {"label": {"type": "string", "default": ""}},
        },
        preview=lambda a: "capture webcam frame",
    )
    def webcam_snapshot(label: str = "") -> str:
        if not _cv_ok:
            return "opencv-python not installed"
        import cv2
        import json as _json
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return "no webcam"
        ok, frame = cap.read()
        cap.release()
        if not ok:
            return "capture failed"
        ts = time.strftime("%Y%m%d-%H%M%S")
        fname = f"webcam-{label or 'frame'}-{ts}.png"
        path = snap_dir / fname
        cv2.imwrite(str(path), frame)
        # Surface inline so the user actually sees it.
        url = f"/api/files/screenshots/{fname}"
        payload = {
            "kind": "image",
            "items": [{
                "url":       url,
                "thumbnail": url,
                "title":     f"webcam capture · {label or 'frame'}",
                "source":    "local cam",
            }],
            "summary": f"Webcam snapshot saved: {fname}",
        }
        return "__JARVIS_MEDIA__" + _json.dumps(payload, ensure_ascii=False)

    @tool(
        name="webcam_see",
        description=(
            "★ ONE-SHOT VISION ON THE WEBCAM — captures a frame AND analyzes "
            "it with the multimodal model in a single tool call. Use this for "
            "ANY 'look at what I'm holding / what am I showing / can you see "
            "this / describe what you see' request. Pushes the frame to the "
            "Media Bay and returns the visual analysis. "
            "DO NOT chain webcam_snapshot + analyze_image manually — call "
            "webcam_see instead."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "default": "Describe in detail what you see in this image. Identify any objects the user is holding or showing.",
                },
            },
        },
        preview=lambda a: "webcam_see (snapshot + vision)",
    )
    async def webcam_see(question: str = "Describe in detail what you see in this image. Identify any objects the user is holding or showing.") -> str:
        if not _cv_ok:
            return "opencv-python not installed"
        import base64, json as _json
        import cv2
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return "no webcam"
        # Discard a few warmup frames — many webcams need 2-3 reads to expose properly.
        for _ in range(4):
            cap.read()
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return "webcam capture failed"
        # Save + encode
        ts = time.strftime("%Y%m%d-%H%M%S")
        fname = f"webcam-see-{ts}.png"
        path = snap_dir / fname
        cv2.imwrite(str(path), frame)
        ok_enc, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not ok_enc:
            return f"saved {path} but encoding failed"
        b64 = base64.b64encode(buf.tobytes()).decode()
        data_url = f"data:image/jpeg;base64,{b64}"

        # Multimodal call
        brain = registry.services.get("brain")
        if brain is None:
            from ..core.brain import LLMBrain
            brain = LLMBrain(registry.cfg)
            close_after = True
        else:
            close_after = False
        messages = [
            {"role": "system", "content": "You are a precise vision analyst. Identify objects, colors, text, hand positions. Be specific."},
            {"role": "user", "content": question, "attachments": [{"type": "image", "data_url": data_url}]},
        ]
        try:
            reply = await brain.chat(messages, tool_schemas=[])
            analysis = reply.text or "(no vision output)"
        except Exception as e:  # noqa: BLE001
            analysis = f"vision call failed: {e}"
        finally:
            if close_after:
                await brain.aclose()

        # Push to Media Bay so user sees the frame too. The summary becomes
        # the text the model sees as the tool result (orchestrator extracts
        # `summary` from the media payload), so put the full analysis there.
        url = f"/api/files/screenshots/{fname}"
        media = {
            "kind": "image",
            "items": [{
                "url":       url,
                "thumbnail": url,
                "title":     f"webcam frame · {ts}",
                "snippet":   analysis[:280],
                "source":    "local cam",
            }],
            "summary": f"Webcam analysis:\n{analysis}",
        }
        return "__JARVIS_MEDIA__" + _json.dumps(media, ensure_ascii=False)

    @tool(
        name="analyze_image",
        description=(
            "VISION Q&A on an already-saved image file. Use for screenshots "
            "OR webcam frames captured in a previous step. For 'look at me / "
            "what am I holding' the correct first call is `webcam_see` "
            "(which combines snapshot + analysis)."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "path":     {"type": "string"},
                "question": {"type": "string", "default": "Describe what you see in detail."},
            },
            "required": ["path"],
        },
        preview=lambda a: f"vision: analyze {a.get('path','?')}",
    )
    async def analyze_image(path: str, question: str = "Describe what you see in detail.") -> str:
        import base64, mimetypes
        from ..core.brain import LLMBrain
        from ..utils.files import expand
        # Accept absolute path, project-relative, or /api/files/... URL.
        p_raw = path
        if p_raw.startswith("/api/files/"):
            rel = p_raw[len("/api/files/"):]
            p = registry.cfg.abs_path("data/" + rel)
        else:
            p = expand(p_raw)
            if not p.is_absolute():
                p = registry.cfg.abs_path(str(p))
        if not p.exists():
            return f"not found: {p}"
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode()
        data_url = f"data:{mime};base64,{b64}"

        brain: LLMBrain = registry.services.get("brain")  # injected at startup
        # Fall back to a fresh brain if services dict doesn't have one.
        if brain is None:
            brain = LLMBrain(registry.cfg)
            close_after = True
        else:
            close_after = False

        messages = [
            {"role": "system", "content": "You are a vision analyst. Be concise, factual, structured."},
            {
                "role": "user",
                "content": question,
                "attachments": [{"type": "image", "data_url": data_url}],
            },
        ]
        try:
            reply = await brain.chat(messages, tool_schemas=[])
            return reply.text or "(no analysis)"
        finally:
            if close_after:
                await brain.aclose()

    registry.add_pending("vision_tools_optional")
    registry.register_plugin(PluginInfo(
        name="vision_tools_optional",
        description="OPTIONAL vision: screenshots, OCR, webcam capture, vision Q&A.",
        permissions_needed=[Permission.CAUTION, Permission.DANGEROUS],
    ))
