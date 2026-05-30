"""REST routes."""
from __future__ import annotations

import asyncio
import base64
import collections
import io
import json
import logging
import os
import platform
import re
import shutil
import tempfile
import wave
from pathlib import Path
from urllib.parse import urlparse

import httpx
import psutil
from fastapi import APIRouter, Form, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

router = APIRouter()
_stt_log = logging.getLogger("jarvis.stt")

# ── VRAM manager integration ────────────────────────────────────────────────
from ..core.vram_manager import (
    GPUResource,
    apply_vram_cap,
    flush_gpu as _vram_flush,
    register_eviction,
)
import threading
_whisper_lock = threading.Lock()  # prevent STT during GPU eviction


# Whisper's training set was dominated by YouTube subtitles. On near-silent
# or noisy clips the LM emits canned outros — "thank you for watching",
# "please subscribe", lone "thanks", "you", "." — even with VAD on. We
# pattern-match these and discard so they never reach the chat loop.
_HALLUCINATION_RE = re.compile(
    r"""^\s*
    (?:
      thanks?[\s,.!?]*(?:for\s+watching|for\s+listening)?[\s,.!?]*
      (?:everyone|guys|all)?[\s,.!?]*
    | thank\s+you[\s,.!?]*(?:for\s+watching|for\s+listening|so\s+much)?[\s,.!?]*
    | (?:please\s+)?(?:like\s*(?:and\s+)?)?subscribe[\s,.!?]*(?:to\s+my\s+channel)?[\s,.!?]*
    | bye(?:\s*bye)?[\s,.!?]*
    | goodbye[\s,.!?]*
    | (?:see|catch)\s+you\s+(?:later|next\s+time)[\s,.!?]*
    | you[\s,.!?]*
    | (?:oh|ohh+|uh|uhh+|um|umm+|hmm+|hm|ah|ahh+|aha|eh|ehh+|mm+|er|err+
        |huh|ugh|oof|whoa|oops|mhm|uh[\s-]*huh|oh\s+my)[\s,.!?…]*
    | [.!?,…\s♪♫]+
    )
    \s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def _filter_whisper_hallucination(text: str) -> str:
    """Return empty string for transcripts that match the hallucination
    blocklist; otherwise return the input unchanged."""
    if not text:
        return ""
    stripped = text.strip()
    if len(stripped) <= 1:
        return ""
    if _HALLUCINATION_RE.match(stripped):
        _stt_log.info("STT: discarded hallucinated transcript: %r", stripped)
        return ""
    return text

# ── Live log streaming ───────────────────────────────────────────────────────
# A lightweight SSE log sink: last 300 records in memory, broadcast to all
# connected clients via per-client asyncio.Queue.

_LOG_BUFFER: collections.deque = collections.deque(maxlen=300)
_LOG_QUEUES: set[asyncio.Queue] = set()
_LOG_LOOP: asyncio.AbstractEventLoop | None = None


class _SSELogHandler(logging.Handler):
    """Captures every log record, stores it, and fans out to live SSE clients."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts":    record.created,
                "level": record.levelname,
                "name":  record.name,
                "msg":   self.format(record),
            }
            _LOG_BUFFER.append(entry)
            loop = _LOG_LOOP
            if loop and loop.is_running():
                for q in list(_LOG_QUEUES):
                    try:
                        loop.call_soon_threadsafe(q.put_nowait, entry)
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            pass


def install_log_handler() -> None:
    """Wire the SSE handler so the in-app terminal sees every log record.

    The `jarvis` logger has `propagate=False` (see core/logger.py), so records
    emitted on `jarvis.*` never reach the root logger. Attach the SSE handler
    to BOTH root (uvicorn, fastapi, asyncio, third-party noise) AND the
    `jarvis` logger (every jarvis.* record). Without this fan-out the in-app
    terminal stays empty even though the console log is busy.
    """
    global _LOG_LOOP
    try:
        _LOG_LOOP = asyncio.get_event_loop()
    except RuntimeError:
        pass
    handler = _SSELogHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))
    # Attach to root + jarvis loggers; guard against duplicate adds.
    for logger_name in ("", "jarvis"):
        lg = logging.getLogger(logger_name)
        if not any(isinstance(h, _SSELogHandler) for h in lg.handlers):
            lg.addHandler(handler)
        if logger_name == "jarvis" and lg.level > logging.DEBUG:
            lg.setLevel(logging.DEBUG)


@router.get("/logs")
async def get_logs(n: int = 200):
    """Return the last `n` log records as JSON."""
    records = list(_LOG_BUFFER)[-n:]
    return {"logs": records, "total": len(_LOG_BUFFER)}


@router.get("/logs/stream")
async def stream_logs(request: Request):
    """Server-Sent Events stream of live log lines.

    Clients receive the last 100 buffered records on connect, then new
    records as they arrive.  A heartbeat comment is sent every 15 s so
    proxies don't kill idle connections.
    """
    async def _generate():
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        _LOG_QUEUES.add(q)
        try:
            # Replay recent history.
            for entry in list(_LOG_BUFFER)[-100:]:
                yield f"data: {json.dumps(entry)}\n\n"
            # Stream new events.
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(entry)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"   # keep-alive comment
        finally:
            _LOG_QUEUES.discard(q)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )

JARVIS_TTS_VOICE = "en-GB-ThomasNeural"
NVIDIA_WAVEGLOW_URL = (
    "https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tlt-jarvis/"
    "models/speechsynthesis_waveglow?version=deployable_v1.0"
)


@router.post("/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    """Receive audio from browser MediaRecorder, transcribe with Whisper."""
    import asyncio
    data = await audio.read()
    if not data:
        return JSONResponse({"text": "", "error": "empty audio"}, status_code=400)

    _stt_log.info("STT: received %d bytes", len(data))

    tmp = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
    tmp.write(data)
    tmp.close()

    # Tightened decode kwargs that suppress Whisper's well-known YouTube-style
    # hallucinations ("thank you", "thanks for watching", "subscribe", "."):
    #   * vad_filter — Silero VAD trims silence segments before decoding.
    #   * no_speech_threshold raised — segments with high no-speech probability
    #     are dropped instead of being decoded into junk.
    #   * log_prob_threshold + compression_ratio_threshold cull low-confidence
    #     repetitive output.
    #   * temperature=0 — deterministic greedy decode, no sampled fallback.
    #   * initial_prompt biases the LM away from the YouTube-style outro
    #     phrases and toward technical assistant vocabulary.
    _WHISPER_KW: dict = dict(
        language="en",
        beam_size=1,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400, "threshold": 0.45},
        condition_on_previous_text=False,
        no_speech_threshold=0.7,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
        temperature=0.0,
        initial_prompt=(
            "JARVIS command. Search, generate image, open page, run code, "
            "show news, list videos, open the file."
        ),
    )

    def _post_process(text: str) -> str:
        """Drop common Whisper hallucinations on near-silent audio."""
        return _filter_whisper_hallucination(text)

    def _run_whisper(path: str) -> str:
        with _whisper_lock:  # Prevent STT during GPU eviction
            model = _get_whisper_model()
            try:
                segments, _ = model.transcribe(path, **_WHISPER_KW)
                return _post_process(" ".join(seg.text.strip() for seg in segments).strip())
            except (OSError, RuntimeError) as e:
                # Common failure: CUDA runtime DLL not loadable (cufft64_11.dll,
                # cudnn, etc.). The model loaded earlier but transcription needs
                # additional DLLs that aren't on PATH. Drop the cached GPU model
                # and rebuild on CPU once; retry transcription.
                msg = str(e)
                if "out of memory" in msg.lower():
                    _stt_log.warning("STT: CUDA OOM — switching to CPU for this run. Detail: %s", e)
                    _vram_flush()
                    _switch_whisper_to_cpu()
                    model = _get_whisper_model()
                    segments, _ = model.transcribe(path, **_WHISPER_KW)
                    return _post_process(" ".join(seg.text.strip() for seg in segments).strip())
                if any(s in msg.lower() for s in ("winerror 193", "cufft", "cudnn", "cublas", "not a valid win32", "could not load")):
                    _stt_log.warning("STT: GPU transcription DLL failure — switching to CPU permanently. Detail: %s", e)
                    _switch_whisper_to_cpu()
                    model = _get_whisper_model()
                    segments, _ = model.transcribe(path, **_WHISPER_KW)
                    return _post_process(" ".join(seg.text.strip() for seg in segments).strip())
                raise

    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, _run_whisper, tmp.name)
        _stt_log.info("STT: transcript = '%s'", text)
        return {"text": text}
    except Exception as e:
        _stt_log.error("STT: Whisper failed: %s", e)
        return JSONResponse({"text": "", "error": f"Whisper error: {e}"}, status_code=500)
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


# Cached Whisper model (loaded once, reused). When GPU runtime is broken
# we permanently switch to CPU for this process — never thrash mid-request.
_whisper_model = None
_whisper_device = None    # "cuda" | "cpu" | None


def _switch_whisper_to_cpu() -> None:
    global _whisper_model, _whisper_device
    _whisper_model = None
    _whisper_device = "cpu"


def _evict_whisper_from_gpu() -> None:
    """Eviction callback retained for API parity, but Whisper-turbo (~1.5 GB)
    + FLUX Q6_K (~6 GB) coexist comfortably on a 16 GB GPU. We therefore
    keep Whisper resident across image-gen runs so STT stays instant. Set
    EVICT_WHISPER_FOR_FLUX=1 in the env to restore the old behaviour on
    tighter cards.
    """
    if os.getenv("EVICT_WHISPER_FOR_FLUX", "0") != "1":
        return
    global _whisper_model, _whisper_device
    with _whisper_lock:
        if _whisper_model is not None:
            _stt_log.info("Evicting Whisper from GPU (VRAM manager request)")
            del _whisper_model
            _whisper_model = None
            _vram_flush()
            _stt_log.info("Whisper evicted — VRAM freed")


def _restore_whisper_to_gpu() -> None:
    """Called by the VRAM manager after another subsystem (FLUX) is done.
    Lazy-restores: the actual model load happens on next STT request."""
    global _whisper_model
    # Don't eagerly reload — let it lazy-load on next _get_whisper_model() call.
    # Just log that it's available to reload.
    _stt_log.info("Whisper restore available (will lazy-load on next STT request)")


def _whisper_cuda_runtime_ok() -> bool:
    """Probe whether the CUDA runtime DLLs cuFFT/cuBLAS/cuDNN that
    faster-whisper/ctranslate2 needs actually load on this box. Avoids the
    'load model on GPU then crash mid-transcribe' trap.

    Also opportunistically adds nvidia-* pip-wheel DLL dirs to the DLL
    search path so users who installed `nvidia-cublas-cu12`,
    `nvidia-cudnn-cu12`, `nvidia-cufft-cu12` don't have to mess with PATH.
    """
    if os.name != "nt":
        return True
    import ctypes
    import sys
    # Add bundled NVIDIA pip-wheel DLLs to the DLL search path.
    try:
        site_packages = Path(sys.executable).resolve().parent.parent / "Lib" / "site-packages"
        nvidia_root = site_packages / "nvidia"
        if nvidia_root.is_dir():
            for pkg in nvidia_root.iterdir():
                bin_dir = pkg / "bin"
                if bin_dir.is_dir():
                    try:
                        os.add_dll_directory(str(bin_dir))
                    except (OSError, AttributeError):
                        pass
    except Exception:  # noqa: BLE001
        pass

    candidates = ["cublas64_12.dll", "cublas64_11.dll", "cudnn64_9.dll",
                  "cudnn64_8.dll", "cufft64_11.dll", "cufft64_10.dll"]
    found = 0
    for dll in candidates:
        try:
            ctypes.WinDLL(dll)
            found += 1
        except OSError:
            pass
    return found >= 2


def _get_whisper_model():
    global _whisper_model, _whisper_device
    if _whisper_model is not None:
        return _whisper_model
    from faster_whisper import WhisperModel

    # Apply VRAM hard cap before loading any GPU model.
    apply_vram_cap()

    # Forced CPU mode (set after a runtime failure).
    if _whisper_device == "cpu":
        _stt_log.info("Loading Whisper 'small' on CPU (int8)…")
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
        _stt_log.info("Whisper small loaded on CPU.")
        return _whisper_model

    # First-time load: probe CUDA runtime before touching the GPU model.
    if _whisper_cuda_runtime_ok():
        try:
            # large-v3-turbo: same quality as large-v3, ~8× faster decoding,
            # ~1.5 GB VRAM (vs ~3 GB for large-v3). Lets Whisper stay loaded
            # alongside FLUX on a 16 GB card without thrash.
            _stt_log.info("Loading Whisper 'large-v3-turbo' on GPU (float16)…")
            _whisper_model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
            _whisper_device = "cuda"
            _stt_log.info("Whisper large-v3-turbo loaded on GPU.")
            # Register eviction callbacks with the VRAM manager so FLUX
            # can kick Whisper off GPU when it needs the memory.
            register_eviction(
                GPUResource.WHISPER,
                evict_fn=_evict_whisper_from_gpu,
                restore_fn=_restore_whisper_to_gpu,
            )
            return _whisper_model
        except Exception as e:  # noqa: BLE001
            _stt_log.warning("GPU model load failed (%s) — falling back to CPU.", e)
    else:
        _stt_log.warning(
            "CUDA runtime DLLs (cuBLAS/cuDNN/cuFFT) not loadable on this host. "
            "Whisper will run on CPU. Install the NVIDIA CUDA Toolkit (12.x) "
            "or the CUDA runtime libraries from NVIDIA to enable GPU STT."
        )

    _whisper_device = "cpu"
    _stt_log.info("Loading Whisper 'small' on CPU (int8)…")
    _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    _stt_log.info("Whisper small loaded on CPU.")
    return _whisper_model


def _services(req: Request):
    s = req.app.state
    return s.cfg, s.orchestrator, s.registry, s.memory, s.agents


@router.get("/health")
async def health(request: Request):
    cfg, orch, registry, memory, agents = _services(request)
    return {
        "status": "online",
        "name": cfg.A.name,
        "model": {
            "provider": cfg.model.provider,
            "model": cfg.model.model,
            "endpoint": cfg.model.endpoint,
            "configured": bool(cfg.model.api_key),
        },
        "image_model": getattr(getattr(cfg, "image_model", None), "selected", "flux2-klein"),
        "plugins": [p.name for p in registry.plugins()],
        "tools": len(registry.all_tools()),
        "agents": agents.names(),
        "permission_mode": cfg.permissions.mode,
    }


class ImageModelSelectBody(BaseModel):
    model: str


@router.get("/image-models")
async def image_models(request: Request):
    cfg = request.app.state.cfg
    from ..plugins.media_generation import list_image_models
    return list_image_models(cfg)


@router.post("/image-models/select")
async def select_image_model_endpoint(request: Request, body: ImageModelSelectBody):
    cfg = request.app.state.cfg
    from ..plugins.media_generation import select_image_model
    try:
        return {"ok": True, **select_image_model(cfg, body.model)}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.get("/stats")
async def stats(request: Request):
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    root = "C:\\" if platform.system() == "Windows" else "/"
    disk = psutil.disk_usage(root)
    net = psutil.net_io_counters()
    b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    out = {
        "cpu": cpu,
        "cpu_count": psutil.cpu_count(logical=True),
        "ram": {"percent": mem.percent, "used_gb": mem.used / 1e9, "total_gb": mem.total / 1e9},
        "disk": {"percent": disk.percent, "used_gb": disk.used / 1e9, "total_gb": disk.total / 1e9},
        "net": {"sent_mb": net.bytes_sent / 1e6, "recv_mb": net.bytes_recv / 1e6},
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "node": platform.node(),
        },
        "gpu": _read_gpu(),
    }
    if b is not None:
        out["battery"] = {"percent": b.percent, "plugged": b.power_plugged}
    return out


# --- GPU telemetry ---------------------------------------------------------
_gpu_log = logging.getLogger("jarvis.gpu")
_pynvml = None
_pynvml_failed = False


def _try_pynvml():
    """Lazy-init NVML. Returns the module or None."""
    global _pynvml, _pynvml_failed
    if _pynvml is not None or _pynvml_failed:
        return _pynvml
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        _pynvml = pynvml
        return _pynvml
    except Exception as e:  # noqa: BLE001
        _pynvml_failed = True
        _gpu_log.info("pynvml unavailable (%s) — falling back to nvidia-smi", e)
        return None


def _read_gpu() -> dict:
    """Read GPU utilisation via NVML (preferred) or nvidia-smi fallback.

    Returns:
      {available, name, load_percent, mem_percent, mem_used_gb, mem_total_gb, temp_c}
    """
    nv = _try_pynvml()
    if nv is not None:
        try:
            count = nv.nvmlDeviceGetCount()
            if count == 0:
                return {"available": False}
            h = nv.nvmlDeviceGetHandleByIndex(0)
            util = nv.nvmlDeviceGetUtilizationRates(h)
            meminfo = nv.nvmlDeviceGetMemoryInfo(h)
            try:
                temp = nv.nvmlDeviceGetTemperature(h, 0)  # NVML_TEMPERATURE_GPU = 0
            except Exception:
                temp = None
            name = nv.nvmlDeviceGetName(h)
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            return {
                "available":   True,
                "source":      "nvml",
                "name":        name,
                "load_percent": float(util.gpu),
                "mem_percent":  float(util.memory),
                "mem_used_gb":  meminfo.used  / 1e9,
                "mem_total_gb": meminfo.total / 1e9,
                "temp_c":       temp,
            }
        except Exception as e:  # noqa: BLE001
            _gpu_log.debug("nvml query failed: %s", e)
    # nvidia-smi fallback
    smi = shutil.which("nvidia-smi")
    if not smi:
        return {"available": False}
    try:
        import subprocess
        out = subprocess.check_output(
            [smi, "--query-gpu=name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            timeout=2, text=True, stderr=subprocess.DEVNULL,
        )
        line = out.strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            return {"available": False}
        return {
            "available":    True,
            "source":       "nvidia-smi",
            "name":         parts[0],
            "load_percent": float(parts[1] or 0),
            "mem_percent":  float(parts[2] or 0),
            "mem_used_gb":  float(parts[3] or 0) / 1024.0,
            "mem_total_gb": float(parts[4] or 0) / 1024.0,
            "temp_c":       float(parts[5] or 0),
        }
    except Exception as e:  # noqa: BLE001
        _gpu_log.debug("nvidia-smi fallback failed: %s", e)
        return {"available": False}


@router.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    """Drag-drop upload sink. Saves under data/uploads/<uuid-name> and returns
    the public URL. Used by the drop-zone overlay for non-image files (and
    images that exceed the inline base64 cap)."""
    import uuid
    cfg = request.app.state.cfg
    up_dir = cfg.abs_path("data/uploads")
    up_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename or "blob")
    uid = uuid.uuid4().hex[:8]
    out_path = up_dir / f"{uid}-{safe_name}"
    data = await file.read()
    if not data:
        return JSONResponse({"error": "empty file"}, status_code=400)
    out_path.write_bytes(data)
    # Build a data_url for images so the frontend can preview inline.
    data_url = None
    if file.content_type and file.content_type.startswith("image/"):
        b64 = base64.b64encode(data).decode("ascii")
        data_url = f"data:{file.content_type};base64,{b64}"
    return {
        "ok": True,
        "name": file.filename,
        "url": f"/api/files/uploads/{out_path.name}",
        "data_url": data_url,
        "size": len(data),
        "mime": file.content_type,
    }


_ALLOWED_FILE_ROOTS = {
    "screenshots", "voices", "backups", "sandbox", "uploads", "generated",
}


@router.get("/files/{full_path:path}")
async def serve_data_file(request: Request, full_path: str):
    """Serve files from `data/<allowlisted_root>/...`. Path-traversal safe.

    Each top-level component (the "root") must be in `_ALLOWED_FILE_ROOTS`.
    Subdirectories beneath that root are allowed so callers can use nested
    layouts like `generated/images/foo.png` or `generated/models3d/x.glb`.
    """
    from fastapi.responses import FileResponse
    cfg = request.app.state.cfg
    if not full_path:
        return JSONResponse({"error": "empty path"}, status_code=400)
    # Normalise + traversal-block.
    norm = full_path.replace("\\", "/").lstrip("/")
    if ".." in norm.split("/") or norm.startswith("."):
        return JSONResponse({"error": "bad path"}, status_code=400)
    root = norm.split("/", 1)[0]
    if root not in _ALLOWED_FILE_ROOTS:
        return JSONResponse({"error": f"root '{root}' not allowed"}, status_code=403)
    p = cfg.abs_path("data") / norm
    # Final containment check: resolved path must still live under data/.
    data_root = cfg.abs_path("data").resolve()
    try:
        resolved = p.resolve()
        resolved.relative_to(data_root)
    except (OSError, ValueError):
        return JSONResponse({"error": "path escaped"}, status_code=400)
    if not resolved.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(resolved)


@router.get("/processes")
async def processes(request: Request, limit: int = 15):
    rows = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            rows.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    rows.sort(key=lambda x: (x.get("cpu_percent") or 0), reverse=True)
    return {"processes": rows[:limit]}


@router.get("/tools")
async def tools(request: Request):
    cfg, orch, registry, *_ = _services(request)
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "permission": t.permission.value,
                "plugin": t.plugin,
                "parameters": t.parameters,
            }
            for t in registry.all_tools()
        ]
    }


@router.get("/plugins")
async def plugins(request: Request):
    cfg, orch, registry, *_ = _services(request)
    return {
        "plugins": [
            {
                "name": p.name,
                "description": p.description,
                "permissions": [perm.value for perm in p.permissions_needed],
            }
            for p in registry.plugins()
        ]
    }


@router.get("/agents")
async def list_agents(request: Request):
    *_, agents = _services(request)
    return {
        "agents": [
            {"name": a.name, "description": a.description, "tools": a.tool_allowlist}
            for a in agents.list()
        ]
    }


@router.get("/intents")
async def list_intents_endpoint(_request: Request):
    """List every deterministic intent the router can classify. Useful for
    UI surfacing + debugging tool selection regressions."""
    from ..core.intent_router import list_intents
    return {"intents": list_intents()}


@router.get("/intents/classify")
async def classify_endpoint(text: str):
    """Dry-run intent classification on arbitrary text. The router does NOT
    execute any tool — it just reports which intent (if any) would fire.
    Lets you verify routing without spending an LLM call."""
    from ..core.intent_router import classify
    m = classify(text)
    if m is None:
        return {"matched": False, "intent": None}
    return {
        "matched": True,
        "intent": m.name,
        "tool": m.tool_call.name,
        "args": m.tool_call.args,
        "final_prefix": m.final_prefix,
        "raw_match": m.raw_match,
    }


@router.get("/memory/prefs")
async def get_prefs(request: Request):
    *_, memory, _ = _services(request)
    return {"prefs": memory.all_prefs()}


@router.get("/memory/notes")
async def get_notes(request: Request, project: str | None = None):
    *_, memory, _ = _services(request)
    return {"notes": memory.notes(project)}


@router.get("/memory/paths")
async def get_paths(request: Request):
    *_, memory, _ = _services(request)
    return {"paths": memory.list_paths()}


@router.get("/memory/tools")
async def get_known_tools(request: Request):
    *_, memory, _ = _services(request)
    return {"tools": memory.list_tools()}


@router.get("/memory/search")
async def search_memory(request: Request, q: str, limit: int = 20):
    *_, memory, _ = _services(request)
    return {"hits": memory.search(q, limit=limit)}


@router.get("/memory/conversation")
async def conversation(request: Request, limit: int = 100):
    *_, memory, _ = _services(request)
    return {"messages": memory.recent_messages(limit)}


class PersonaBody(BaseModel):
    persona: str


class TTSBody(BaseModel):
    text: str
    voice: str = JARVIS_TTS_VOICE


@router.get("/persona")
async def get_persona(request: Request):
    cfg, *_ = _services(request)
    return {"persona": cfg.A.persona, "name": cfg.A.name}


@router.post("/persona")
async def set_persona(request: Request, body: PersonaBody):
    cfg, *_ = _services(request)
    cfg.A.persona = body.persona
    return {"ok": True}


@router.get("/tts/status")
async def tts_status(request: Request):
    cfg, *_ = _services(request)
    edge_available = _edge_tts_available()
    riva_client_available = _riva_client_available()
    riva_ready = _riva_enabled(cfg) and riva_client_available
    piper_ready = _piper_available(cfg)

    if piper_ready:
        provider, label, voice, lang = "piper", "JARVIS (Piper, community model)", "jarvis", "en-GB"
    elif riva_ready:
        provider, label, voice, lang = "nvidia-riva", "NVIDIA Riva / Jarvis TTS", cfg.voice.riva_voice, cfg.voice.riva_language_code
    else:
        provider = "edge-tts"
        label = "Microsoft Ryan Neural (British male)"
        voice = cfg.voice.edge_voice
        lang = "en-GB"

    return {
        "available": edge_available or riva_ready or piper_ready,
        "provider": provider,
        "requested_provider": cfg.voice.provider,
        "voice": voice,
        "label": label,
        "lang": lang,
        "providers": {
            "piper": {
                "enabled":  bool(getattr(cfg.voice, "piper_enabled", False)),
                "available": piper_ready,
                "model":    str(cfg.abs_path(cfg.voice.piper_model)),
                "note":     "Install: pip install piper-tts. Model: huggingface.co/jgkawell/jarvis (en_GB-jarvis-medium.onnx).",
            },
            "edge_tts": {
                "available": edge_available,
                "voice": cfg.voice.edge_voice,
                "rate":  cfg.voice.edge_rate,
                "pitch": cfg.voice.edge_pitch,
                "label": "Microsoft Ryan Neural",
            },
            "nvidia_riva": {
                "enabled": _riva_enabled(cfg),
                "client_available": riva_client_available,
                "server": cfg.voice.riva_server,
                "voice": cfg.voice.riva_voice,
                "language_code": cfg.voice.riva_language_code,
                "sample_rate_hz": cfg.voice.riva_sample_rate_hz,
                "waveglow_model_url": getattr(cfg.voice, "nvidia_waveglow_model_url", NVIDIA_WAVEGLOW_URL),
                "note": "WaveGlow is a Riva/Jarvis vocoder component; it requires a running Riva TTS server.",
            },
        },
    }


def _piper_available(cfg) -> bool:
    if not _should_try_piper(cfg):
        return False
    try:
        import piper.voice  # type: ignore  # noqa: F401
    except Exception:
        return False
    return Path(cfg.abs_path(cfg.voice.piper_model)).exists()


@router.post("/tts")
async def tts(request: Request, body: TTSBody):
    cfg, *_ = _services(request)
    text = (body.text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "empty text"}, status_code=400)
    text = text[:1800]
    tts_log = logging.getLogger("jarvis.tts")

    # 1. Piper — community JARVIS model (closest to MCU voice).
    if _should_try_piper(cfg):
        try:
            audio = _synthesize_with_piper(text, cfg)
            return Response(audio, media_type="audio/wav", headers={"X-JARVIS-TTS": "piper"})
        except Exception as e:  # noqa: BLE001
            tts_log.warning("Piper TTS failed (%s) — falling back", e)

    # 2. Riva (NVIDIA cloud)
    if _should_try_riva(cfg):
        try:
            audio = _synthesize_with_riva(text, cfg)
            return Response(audio, media_type="audio/wav", headers={"X-JARVIS-TTS": "riva"})
        except Exception as e:  # noqa: BLE001
            tts_log.warning("Riva TTS failed (%s) — falling back to edge-tts", e)

    # 3. Edge TTS (Microsoft Ryan / Thomas Neural)
    voice = body.voice or cfg.voice.edge_voice or "en-GB-ThomasNeural"
    rate  = cfg.voice.edge_rate  or "-6%"
    pitch = cfg.voice.edge_pitch or "+0Hz"
    try:
        import edge_tts
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            {"ok": False, "error": f"edge-tts unavailable: {e}"},
            status_code=503,
        )

    async def stream_audio():
        communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    return StreamingResponse(
        stream_audio(),
        media_type="audio/mpeg",
        headers={"X-JARVIS-TTS": "edge"},
    )


# --- Piper TTS (local, closest match to MCU JARVIS) ------------------------
_piper_voice = None
_piper_failed = False


def _should_try_piper(cfg) -> bool:
    provider = (cfg.voice.provider or "auto").lower().strip()
    if provider == "piper":
        return True
    return provider == "auto" and bool(getattr(cfg.voice, "piper_enabled", False))


def _synthesize_with_piper(text: str, cfg) -> bytes:
    global _piper_voice, _piper_failed
    if _piper_failed:
        raise RuntimeError("piper init failed previously")
    if _piper_voice is None:
        try:
            from piper.voice import PiperVoice  # type: ignore
        except Exception as e:  # noqa: BLE001
            _piper_failed = True
            raise RuntimeError(f"piper-tts not installed: {e}")
        model_path = cfg.abs_path(cfg.voice.piper_model)
        if not Path(model_path).exists():
            _piper_failed = True
            raise RuntimeError(f"piper model not found: {model_path}")
        _piper_voice = PiperVoice.load(str(model_path))

    # piper-tts 1.4+ API: synthesize_wav writes a full WAV stream. Full
    # prosody controls — length, noise, phoneme-timing variability, volume.
    from piper.config import SynthesisConfig  # type: ignore
    syn_cfg = SynthesisConfig(
        speaker_id=cfg.voice.piper_speaker if _piper_voice.config.num_speakers > 1 else None,
        length_scale=cfg.voice.piper_length_scale,
        noise_scale=getattr(cfg.voice, "piper_noise_scale", None),
        noise_w_scale=getattr(cfg.voice, "piper_noise_w_scale", None),
        volume=getattr(cfg.voice, "piper_volume", 1.0),
        normalize_audio=True,
    )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        _piper_voice.synthesize_wav(text, wf, syn_config=syn_cfg)
    return buf.getvalue()


def _edge_tts_available() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _riva_client_available() -> bool:
    try:
        import riva.client  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _riva_enabled(cfg) -> bool:
    provider = (cfg.voice.provider or "auto").lower().strip()
    return provider == "nvidia_riva" or bool(cfg.voice.riva_enabled)


def _should_try_riva(cfg) -> bool:
    provider = (cfg.voice.provider or "auto").lower().strip()
    return provider == "nvidia_riva" or (provider == "auto" and bool(cfg.voice.riva_enabled))


# ---------- NVIDIA Riva Cloud TTS ----------
# Uses NVIDIA's hosted API at grpc.nvcf.nvidia.com:443 (no Docker needed).
# Requires NVIDIA_API_KEY in .env (get free at build.nvidia.com).

_RIVA_CLOUD_URI = "grpc.nvcf.nvidia.com:443"
_RIVA_FUNCTION_ID = "877104f7-e885-42b9-8de8-f6e4c6303969"  # magpie-tts-multilingual

_riva_auth = None
_riva_tts_service = None
_riva_resolved_voice: str | None = None
_riva_init_failed = False

import logging as _logging
_riva_log = _logging.getLogger("jarvis.riva")


def _get_riva_service(cfg):
    """Return (auth, tts_service, voice_name) or raise on failure."""
    global _riva_auth, _riva_tts_service, _riva_resolved_voice, _riva_init_failed

    if _riva_init_failed:
        raise RuntimeError("Riva init previously failed; skipping until restart.")

    if _riva_tts_service is not None and _riva_resolved_voice:
        return _riva_auth, _riva_tts_service, _riva_resolved_voice

    try:
        import riva.client
    except ImportError as e:
        _riva_init_failed = True
        raise RuntimeError(
            "riva.client not installed. Run: pip install nvidia-riva-client"
        ) from e

    # Get NVIDIA API key
    api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if not api_key:
        _riva_init_failed = True
        raise RuntimeError(
            "NVIDIA_API_KEY not set in .env. "
            "Get a free key at https://build.nvidia.com → Generate API Key"
        )

    # Check if user has a local Riva server configured
    server = cfg.voice.riva_server or ""
    if server and server != "localhost:50051" and "nvcf.nvidia.com" not in server:
        # User has a custom local Riva server — use it directly
        _riva_log.info("Connecting to local Riva TTS at %s …", server)
        try:
            auth = riva.client.Auth(uri=server)
        except Exception as e:
            _riva_init_failed = True
            raise RuntimeError(f"Local Riva connection failed ({server}): {e}") from e
    else:
        # Use NVIDIA cloud API
        _riva_log.info("Connecting to NVIDIA Riva Cloud TTS …")
        try:
            auth = riva.client.Auth(
                use_ssl=True,
                uri=_RIVA_CLOUD_URI,
                metadata_args=[
                    ["function-id", _RIVA_FUNCTION_ID],
                    ["authorization", f"Bearer {api_key}"],
                ],
            )
        except Exception as e:
            _riva_init_failed = True
            _riva_log.error("Riva cloud auth failed: %s", e)
            raise RuntimeError(f"Riva cloud connection failed: {e}") from e

    try:
        tts_service = riva.client.SpeechSynthesisService(auth)
    except Exception as e:
        _riva_init_failed = True
        raise RuntimeError(f"Riva TTS service init failed: {e}") from e

    # Try the configured voice first, then discover.
    voice = cfg.voice.riva_voice or "Magpie-Multilingual.EN-US.Leo"
    fallback_voices = [
        "Magpie-Multilingual.EN-US.Leo",
        "Magpie-Multilingual.EN-US.Male.Neutral",
        "Magpie-Multilingual.EN-US.Male.Calm",
        "English-US.Male-1",
    ]

    for try_voice in [voice] + [v for v in fallback_voices if v != voice]:
        try:
            _test_riva_synth(tts_service, try_voice, cfg)
            voice = try_voice
            _riva_log.info("Riva voice confirmed: %s", voice)
            break
        except Exception as e:
            _riva_log.warning("Voice '%s' failed: %s", try_voice, e)
    else:
        _riva_init_failed = True
        raise RuntimeError(
            f"No working Riva voice found. Tried: {[voice] + fallback_voices}. "
            f"Check NVIDIA_API_KEY and Riva service status."
        )

    _riva_auth = auth
    _riva_tts_service = tts_service
    _riva_resolved_voice = voice
    return auth, tts_service, voice


def _test_riva_synth(tts_service, voice: str, cfg) -> None:
    """Synthesize a tiny phrase to verify the voice works."""
    import riva.client
    tts_service.synthesize(
        "test",
        voice_name=voice,
        language_code=cfg.voice.riva_language_code or "en-US",
        encoding=riva.client.AudioEncoding.LINEAR_PCM,
        sample_rate_hz=cfg.voice.riva_sample_rate_hz or 44100,
    )


def _synthesize_with_riva(text: str, cfg) -> bytes:
    import riva.client

    _, tts_service, voice = _get_riva_service(cfg)
    sample_rate = cfg.voice.riva_sample_rate_hz or 44100
    lang = cfg.voice.riva_language_code or "en-US"

    resp = tts_service.synthesize(
        text,
        voice_name=voice,
        language_code=lang,
        encoding=riva.client.AudioEncoding.LINEAR_PCM,
        sample_rate_hz=sample_rate,
    )
    return _pcm16_to_wav(resp.audio, sample_rate_hz=sample_rate)


def _pcm16_to_wav(audio: bytes, sample_rate_hz: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate_hz)
        wf.writeframes(audio)
    return buf.getvalue()


# ============================ Iframable proxy ===============================
# Many sites set `X-Frame-Options: DENY` or CSP `frame-ancestors`. To embed
# them inside the Media Bay iframe we proxy the response and strip those
# headers + rewrite relative URLs to absolute. Same-origin policy in the
# iframe is then JARVIS's own origin.

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "x-frame-options", "content-security-policy", "content-security-policy-report-only",
    "permissions-policy", "cross-origin-opener-policy", "cross-origin-embedder-policy",
    "cross-origin-resource-policy",
}


@router.get("/proxy")
async def iframe_proxy(url: str = Query(..., min_length=8)):
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    parsed = urlparse(u)
    if not parsed.netloc:
        return JSONResponse({"error": "bad url"}, status_code=400)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=headers) as c:
            r = await c.get(u)
    except Exception as e:  # noqa: BLE001
        return HTMLResponse(f"<pre>Proxy error: {e}</pre>", status_code=502)

    ctype = r.headers.get("content-type", "text/html")
    out_headers = {
        k: v for k, v in r.headers.items()
        if k.lower() not in _HOP_BY_HOP and not k.lower().startswith("set-cookie")
    }
    out_headers["X-JARVIS-Proxied"] = "1"

    if "html" in ctype.lower():
        text = r.text
        base = f"{parsed.scheme}://{parsed.netloc}"
        # Inject <base> so relative URLs resolve. Strip frame-busting scripts (best-effort).
        base_tag = f'<base href="{base}/">'
        if re.search(r"<head[^>]*>", text, re.IGNORECASE):
            text = re.sub(r"(<head[^>]*>)", r"\1" + base_tag, text, count=1, flags=re.IGNORECASE)
        else:
            text = base_tag + text
        # Remove the common "if (top !== self) top.location = …" bombs.
        text = re.sub(r"if\s*\(\s*(?:top|window\.top)\s*!?=+\s*(?:self|window)[\s\S]*?\)\s*[\s\S]*?;", "", text, count=4)
        return HTMLResponse(text, status_code=r.status_code, headers=out_headers)

    return Response(content=r.content, status_code=r.status_code, media_type=ctype, headers=out_headers)


# ============================ In-app reader =================================
# News URLs frequently can't be iframed (X-Frame-Options DENY, CSP, JS-based
# redirect wrappers like Google News). The reader endpoint server-side
# fetches the article, follows any redirect wrapper to the real publisher,
# strips out boilerplate via trafilatura, and returns a clean JSON payload
# that the frontend renders inside its own themed reader overlay.

_GNEWS_RE = re.compile(r"^https?://(?:www\.)?news\.google\.com/", re.IGNORECASE)
_GNEWS_LINK_RE = re.compile(
    r'<a[^>]+href="(https?://(?!(?:www\.)?(?:news\.)?google\.com)[^"#]+)"',
    re.IGNORECASE,
)


async def _resolve_news_url(url: str) -> str:
    """Resolve Google News wrapper URLs to the real publisher URL."""
    if not _GNEWS_RE.match(url):
        return url
    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0 Safari/537.36",
            },
        ) as c:
            r = await c.get(url)
        final = str(r.url)
        if not _GNEWS_RE.match(final):
            return final
        m = _GNEWS_LINK_RE.search(r.text or "")
        if m:
            return m.group(1)
    except Exception:
        pass
    return url


@router.get("/reader")
async def reader(url: str = Query(..., min_length=8)):
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    real = await _resolve_news_url(u)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as c:
            r = await c.get(real)
        html = r.text or ""
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"fetch failed: {e}"}, status_code=502)

    try:
        import trafilatura
        content_html = trafilatura.extract(
            html,
            url=str(r.url),
            output_format="html",
            include_images=True,
            include_links=True,
            with_metadata=False,
            favor_recall=True,
        ) or ""
        meta_obj = trafilatura.extract_metadata(html, default_url=str(r.url))
        meta: dict = {}
        if meta_obj is not None:
            for k in ("title", "author", "date", "sitename", "image", "description"):
                v = getattr(meta_obj, k, None)
                if v:
                    meta[k] = v
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"extract failed: {e}"}, status_code=500)

    return {
        "ok": True,
        "url": str(r.url),
        "title": meta.get("title") or "",
        "author": meta.get("author") or "",
        "published": meta.get("date") or "",
        "site": meta.get("sitename") or _host(str(r.url)),
        "image": meta.get("image") or "",
        "description": meta.get("description") or "",
        "content_html": content_html,
    }


def _host(url: str) -> str:
    try:
        from urllib.parse import urlparse as _urlparse
        return _urlparse(url).hostname or url
    except Exception:
        return url


@router.post("/cleanslate")
async def clean_slate(request: Request):
    cfg, orch, registry, memory, agents = _services(request)
    orch.reset()
    return {"ok": True, "message": "Clean slate executed. Conversation history wiped. Memory preserved."}


@router.get("/mission")
async def mission(request: Request):
    cfg, *_ = _services(request)
    return {"enabled": cfg.mission.enabled, "project_path": cfg.mission.project_path}


class MissionBody(BaseModel):
    path: str


@router.post("/mission")
async def set_mission(request: Request, body: MissionBody):
    cfg, *_, memory, _ = _services(request)
    from pathlib import Path as _P
    p = _P(body.path).expanduser().resolve()
    if not p.exists():
        return JSONResponse({"ok": False, "error": f"path not found: {p}"}, status_code=400)
    cfg.mission.enabled = True
    cfg.mission.project_path = str(p)
    memory.set_path("mission", str(p), "project")
    return {"ok": True, "path": str(p)}


# ═══════════════════════════════════════════════════════════════════════════
#  IMAGE ANALYSIS / IMG2IMG / IMAGE→3D  endpoints
# ═══════════════════════════════════════════════════════════════════════════

_img_log = logging.getLogger("jarvis.image_api")


@router.post("/analyze-image")
async def analyze_image(
    request: Request,
    file: UploadFile = File(...),
    prompt: str = Form("Describe this image in detail. What do you see?"),
):
    """Send an uploaded image to the LLM for vision analysis.

    The image is base64-encoded and attached as a multimodal content part
    in the OpenAI vision format.  The orchestrator is bypassed — we talk
    directly to the LLMBrain so the response is synchronous JSON.
    """
    data = await file.read()
    if not data:
        return JSONResponse({"error": "empty file"}, status_code=400)
    if not (file.content_type or "").startswith("image/"):
        return JSONResponse({"error": "not an image"}, status_code=400)

    # Cap at 20 MB to avoid absurd payloads.
    if len(data) > 20 * 1024 * 1024:
        return JSONResponse({"error": "image too large (max 20 MB)"}, status_code=400)

    b64 = base64.b64encode(data).decode("ascii")
    mime = file.content_type or "image/png"
    data_url = f"data:{mime};base64,{b64}"

    brain = request.app.state.orchestrator.brain
    cfg = request.app.state.cfg

    messages = [
        {"role": "system", "content": cfg.A.persona.strip()},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    _img_log.info("analyze-image: %d bytes, prompt=%s", len(data), prompt[:80])
    try:
        reply = await brain.chat(messages)
        return {"ok": True, "analysis": reply.text}
    except Exception as e:
        _img_log.exception("analyze-image failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/image-to-3d")
async def image_to_3d_endpoint(
    request: Request,
    file: UploadFile = File(...),
):
    """Upload an image and convert it to a 3D GLB model.

    Uses the media_generation plugin's image_to_3d tool internally.
    Returns the URL to the generated .glb file.
    """
    data = await file.read()
    if not data:
        return JSONResponse({"error": "empty file"}, status_code=400)
    if not (file.content_type or "").startswith("image/"):
        return JSONResponse({"error": "not an image"}, status_code=400)

    cfg = request.app.state.cfg
    registry = request.app.state.registry

    # Save the uploaded image to a temp location.
    up_dir = cfg.abs_path("data/uploads")
    up_dir.mkdir(parents=True, exist_ok=True)
    import uuid as _uuid
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename or "img.png")
    uid = _uuid.uuid4().hex[:8]
    img_path = up_dir / f"{uid}-{safe}"
    img_path.write_bytes(data)

    _img_log.info("image-to-3d: saved %s (%d bytes)", img_path.name, len(data))

    # Invoke the tool directly.
    tool = registry.get("image_to_3d")
    if tool is None:
        return JSONResponse({"error": "image_to_3d tool not available"}, status_code=503)

    try:
        result = await tool.invoke({"image_path": str(img_path)})
        return {"ok": True, "result": result}
    except Exception as e:
        _img_log.exception("image-to-3d failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/img2img")
async def img2img_endpoint(
    request: Request,
    file: UploadFile = File(...),
    prompt: str = Form(""),
    strength: float = Form(0.65),
    steps: int = Form(4),
    guidance_scale: float = Form(4.0),
):
    """Upload an init image + prompt, generate a new image guided by both.

    Uses the media_generation plugin's image_generate tool with init_image.
    Returns the URL to the generated image.
    """
    data = await file.read()
    if not data:
        return JSONResponse({"error": "empty file"}, status_code=400)
    if not (file.content_type or "").startswith("image/"):
        return JSONResponse({"error": "not an image"}, status_code=400)

    cfg = request.app.state.cfg
    registry = request.app.state.registry

    # Save the uploaded image.
    up_dir = cfg.abs_path("data/uploads")
    up_dir.mkdir(parents=True, exist_ok=True)
    import uuid as _uuid
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename or "img.png")
    uid = _uuid.uuid4().hex[:8]
    img_path = up_dir / f"{uid}-{safe}"
    img_path.write_bytes(data)

    _img_log.info("img2img: saved %s (%d bytes), prompt=%s", img_path.name, len(data), prompt[:80])

    tool = registry.get("image_generate")
    if tool is None:
        return JSONResponse({"error": "image_generate tool not available"}, status_code=503)

    args = {
        "prompt": prompt or "transform this image",
        "init_image": str(img_path),
        "strength": strength,
        "steps": steps,
        "guidance_scale": guidance_scale,
    }
    try:
        result = await tool.invoke(args)
        return {"ok": True, "result": result}
    except Exception as e:
        _img_log.exception("img2img failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
