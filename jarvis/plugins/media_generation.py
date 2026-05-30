"""Local AI image + 3D generation tools.

Image: `image_generate(prompt)` — FLUX.2-klein-4B (4B params, Apache 2.0).
       Uses the unsloth Q6_K GGUF file for fast local inference.
       Auto-downloads to  data/models/flux-2-klein-4b-Q6_K.gguf  on first run.

       FLUX.2-klein is Black Forest Labs' fastest distilled model:
         - 4B parameter rectified-flow transformer
         - 4 inference steps (distilled)
         - Q6_K weights: ~3.3 GB on disk, ~6 GB peak VRAM with BF16 activations
         - Fits a 16 GB GPU alongside Whisper-turbo without CPU offload
         - Apache 2.0 — fully open for commercial use

3D:    `image_to_3d(image_path)` - TRELLIS.2 4B FP8 textured pipeline in an
       isolated Python 3.12 worker. It auto-installs/downloads on first use and
       exports textured GLB assets the Media Bay renders inline via
       `<model-viewer>`. The VRAM manager evicts FLUX and Whisper before the
       worker takes the GPU.

All heavy imports + model loads happen LAZILY on first use.
Progress is logged at every diffusion step so the terminal panel shows activity.
"""
from __future__ import annotations

import asyncio
import gc
import hashlib
import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.permissions import Permission
from ..core.vram_manager import (
    GPUResource,
    apply_vram_cap,
    cancel_idle_unload,
    flush_gpu as _flush_gpu,
    gpu_exclusive,
    gpu_exclusive_async,
    register_eviction,
    register_idle_unload,
    schedule_idle_unload,
    safe_cuda_call,
)
from .base import PluginInfo, tool
from ..core.task_progress import report as _progress_report

log = logging.getLogger("jarvis.mediagen")

MEDIA_PREFIX = "__JARVIS_MEDIA__"

# ── Model config ────────────────────────────────────────────────────────────
# GGUF file: unsloth Q6_K quantisation — ~3.3 GB, near-BF16 quality, fast.
_GGUF_REPO   = "unsloth/FLUX.2-klein-4B-GGUF"
_GGUF_FILE   = "flux-2-klein-4b-Q6_K.gguf"
_HF_BASE     = "black-forest-labs/FLUX.2-klein-4B"   # VAE / text-encoders / scheduler

# Pipeline tuning. The Q6_K transformer is only 3.4 GB, BUT the FLUX.2-klein
# text encoder is a ~4B-param LLM = ~8 GB in BF16. Pinning the *whole* pipe on
# CUDA at once (text_encoder 8 GB + transformer 3.4 GB + VAE + 1024² activations
# + CUDA ctx) blows past 16 GB. On Windows the NVIDIA driver then SILENTLY spills
# to system RAM over PCIe ("sysmem fallback") instead of OOMing — GPU sits at
# 100% but every denoise step is PCIe-bound (~255 s first step). So we MUST use
# model_cpu_offload: only the active module sits on GPU (encode → denoise → decode),
# peak VRAM ~8 GB, no spill, full GPU speed. Per-gen cost: one ~1-2 s text-encoder
# swap, vs 100× slowdown from spilling.
_FLUX_IDLE_UNLOAD_S: float = 0.0    # 0 = never unload (stays resident → every gen instant); finite = free VRAM after N s idle
_FLUX_USE_CPU_OFFLOAD = True        # REQUIRED: 8 GB text encoder over-commits 16 GB if fully resident → driver sysmem spill
_FLUX_PRELOAD_AT_STARTUP = False    # load on first image request, not at boot

# -- 3D (Hunyuan3D-2GP Mini Turbo) config -----------------------------------
# The true quantized Hunyuan GGUF options (calcuis/hy3d-gguf) are
# ComfyUI/GGUF-node weights, not loadable by the native hy3dgen runtime without
# embedding a ComfyUI worker. For Jarvis' direct Python tool path, the smallest
# reliable no-access model is Tencent's 0.6B Mini Turbo shape model. It
# downloads only the shape + turbo VAE folders, not the full 25 GB repo.
_HY3DGP_SOURCE_COMMIT = "f2456e036a86a4b1d9f58e2379fe7ab0fe9b68b0"
_HY3DGP_SOURCE_ZIP = (
    "https://github.com/deepbeepmeep/Hunyuan3D-2GP/archive/"
    f"{_HY3DGP_SOURCE_COMMIT}.zip"
)
_HY3D_REPO = "tencent/Hunyuan3D-2mini"
_HY3D_SHAPE_SUBFOLDER = "hunyuan3d-dit-v2-mini-turbo"
_HY3D_VAE_SUBFOLDER = "hunyuan3d-vae-v2-mini-turbo"
_HY3D_KIND = "hunyuan3d-2gp-mini-turbo"
_HY3D_LABEL = "Hunyuan3D-2GP Mini Turbo"
_HY3D_STEPS = 5
_HY3D_GUIDANCE = 5.0
_HY3D_OCTREE_RES = 256
_HY3D_NUM_CHUNKS = 80000
_HY3D_IDLE_UNLOAD_S = 180.0
_HY3D_RETRY_SEEDS = (3407, 1234, 2027)
_HY3D_MC_LEVELS = (0.0, -1.0 / 512.0, 1.0 / 512.0)

# -- 3D (TRELLIS.2 FP8 textured worker) config -------------------------------
_TRELLIS2_KIND = "trellis2-fp8-textured"
_TRELLIS2_LABEL = "TRELLIS.2 FP8 Textured"
_TRELLIS2_MODEL_REPO = "visualbruno/TRELLIS.2-4B-FP8"
_TRELLIS2_WORKER_TIMEOUT_S = int(os.getenv("JARVIS_TRELLIS2_TIMEOUT_S", "1200"))
_TRELLIS2_SETUP_TIMEOUT_S = int(os.getenv("JARVIS_TRELLIS2_SETUP_TIMEOUT_S", "2400"))
_TRELLIS2_DEFAULT_PIPELINE = os.getenv("JARVIS_TRELLIS2_PIPELINE", "512")
_TRELLIS2_DEFAULT_STEPS = int(os.getenv("JARVIS_TRELLIS2_STEPS", "8"))
_TRELLIS2_TEXTURE_STEPS = int(os.getenv("JARVIS_TRELLIS2_TEXTURE_STEPS", str(_TRELLIS2_DEFAULT_STEPS)))
_TRELLIS2_MAX_TOKENS = int(os.getenv("JARVIS_TRELLIS2_MAX_TOKENS", "49152"))
_TRELLIS2_TEXTURE_SIZE = int(os.getenv("JARVIS_TRELLIS2_TEXTURE_SIZE", "1024"))
_TRELLIS2_EXPORT_MODE = os.getenv("JARVIS_TRELLIS2_EXPORT_MODE", "texture").strip().lower()
_TRELLIS2_REMOVE_BACKGROUND = os.getenv("JARVIS_TRELLIS2_REMBG", "1").strip().lower() not in {"0", "false", "no"}


@dataclass(frozen=True)
class ImageModelSpec:
    key: str
    label: str
    family: str
    base_repo: str
    artifact_repo: str
    artifact_file: str
    description: str
    default_steps: int
    default_guidance: float


_DEFAULT_IMAGE_MODEL = "flux2-klein"
_IMAGE_MODEL_ALIASES = {
    "flux": "flux2-klein",
    "flux2": "flux2-klein",
    "flux2-klein-4b": "flux2-klein",
    "flux.2-klein": "flux2-klein",
}
_IMAGE_MODELS: dict[str, ImageModelSpec] = {
    "flux2-klein": ImageModelSpec(
        key="flux2-klein",
        label="FLUX.2-klein-4B Q6_K",
        family="flux2",
        base_repo=_HF_BASE,
        artifact_repo=_GGUF_REPO,
        artifact_file=_GGUF_FILE,
        description="Fast local FLUX.2-klein generator, Q6_K GGUF transformer.",
        default_steps=4,
        default_guidance=4.0,
    ),
}

# Singletons — loaded once per process.
_flux_pipe   = None
_flux_device: str | None = None
_loaded_image_model: str | None = None
_sf3d_model  = None
_sf3d_device: str | None = None
_hy3d_rembg = None      # cached Hunyuan3D background remover

# NOTE: The old _gen_lock is replaced by the centralized VRAM manager's
# gpu_exclusive_async(GPUResource.FLUX) which also evicts Whisper from GPU.


# ── Helpers ─────────────────────────────────────────────────────────────────

def _images_dir(cfg) -> Path:
    p = cfg.abs_path("data/generated/images")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _models_dir(cfg) -> Path:
    p = cfg.abs_path("data/generated/models3d")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _local_models_dir(cfg) -> Path:
    p = cfg.abs_path("data/models")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _normalize_image_model_key(key: str | None) -> str:
    raw = (key or "").strip().lower()
    if not raw:
        raw = _DEFAULT_IMAGE_MODEL
    return _IMAGE_MODEL_ALIASES.get(raw, raw)


def _image_model_spec(cfg, requested: str | None = None) -> ImageModelSpec:
    configured = getattr(getattr(cfg, "image_model", None), "selected", None)
    key = _normalize_image_model_key(requested or configured)
    spec = _IMAGE_MODELS.get(key)
    if spec is None:
        log.warning("Unknown image model '%s'; falling back to %s", key, _DEFAULT_IMAGE_MODEL)
        spec = _IMAGE_MODELS[_DEFAULT_IMAGE_MODEL]
    return spec


def list_image_models(cfg) -> dict[str, Any]:
    selected = _image_model_spec(cfg).key
    models = []
    for spec in _IMAGE_MODELS.values():
        artifact_path = _local_models_dir(cfg) / spec.artifact_file
        models.append({
            "key": spec.key,
            "label": spec.label,
            "family": spec.family,
            "description": spec.description,
            "repo": spec.artifact_repo,
            "file": spec.artifact_file,
            "base_repo": spec.base_repo,
            "local_path": str(artifact_path),
            "downloaded": artifact_path.exists(),
            "loaded": _loaded_image_model == spec.key and _flux_pipe is not None,
            "default_steps": spec.default_steps,
            "default_guidance": spec.default_guidance,
        })
    return {"selected": selected, "models": models}


def select_image_model(cfg, key: str) -> dict[str, Any]:
    normalized = _normalize_image_model_key(key)
    if normalized not in _IMAGE_MODELS:
        raise ValueError(f"unknown image model: {key}")
    spec = _IMAGE_MODELS[normalized]
    image_cfg = getattr(cfg, "image_model", None)
    old_key = _image_model_spec(cfg).key
    if image_cfg is not None:
        image_cfg.selected = spec.key
    if old_key != spec.key and _flux_pipe is not None:
        _unload_flux_pipeline()
    state = list_image_models(cfg)
    return {"selected": spec.key, "model": next(m for m in state["models"] if m["key"] == spec.key)}


def _select_device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _short_hash(s: str, n: int = 8) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:n]


def _fit_size_to_aspect(src_w: int, src_h: int, max_w: int, max_h: int, multiple: int = 16) -> tuple[int, int]:
    if src_w <= 0 or src_h <= 0:
        return max_w, max_h
    max_w = max(multiple, int(max_w))
    max_h = max(multiple, int(max_h))
    scale = min(max_w / src_w, max_h / src_h)
    out_w = max(multiple, int(round((src_w * scale) / multiple)) * multiple)
    out_h = max(multiple, int(round((src_h * scale) / multiple)) * multiple)
    if out_w > max_w:
        out_w = max(multiple, (max_w // multiple) * multiple)
    if out_h > max_h:
        out_h = max(multiple, (max_h // multiple) * multiple)
    return out_w, out_h


def _emit_media(kind: str, items: list[dict], summary: str) -> str:
    return MEDIA_PREFIX + json.dumps(
        {"kind": kind, "items": items, "summary": summary},
        ensure_ascii=False,
    )


# ── GGUF download ────────────────────────────────────────────────────────────

def _ensure_gguf(cfg, spec: ImageModelSpec | None = None) -> str:
    """Return local path to a GGUF file, downloading from HF if absent."""
    spec = spec or _IMAGE_MODELS[_DEFAULT_IMAGE_MODEL]
    dest = _local_models_dir(cfg) / spec.artifact_file
    if dest.exists():
        log.info("%s found at %s (%.1f GB)", spec.label, dest, dest.stat().st_size / 1e9)
        return str(dest)

    log.info(
        "%s not found locally; downloading from %s/%s ...",
        spec.label, spec.artifact_repo, spec.artifact_file,
    )
    _progress_report(
        f"Downloading {spec.label} ({spec.artifact_file}) from Hugging Face..."
    )
    try:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(
            repo_id=spec.artifact_repo,
            filename=spec.artifact_file,
            local_dir=str(_local_models_dir(cfg)),
            local_dir_use_symlinks=False,
        )
        log.info("%s downloaded to %s", spec.label, path)
        return path
    except Exception as e:
        raise RuntimeError(
            f"Failed to download {spec.label}: {e}\n"
            f"Manual download: https://huggingface.co/{spec.artifact_repo}/blob/main/{spec.artifact_file}\n"
            f"Place at: {dest}"
        ) from e


# ── Pipeline loader ──────────────────────────────────────────────────────────

def _load_flux_pipeline(cfg, spec: ImageModelSpec | None = None):
    """Lazy-load FLUX.2-klein-4B with GGUF transformer.

    Strategy:
      1. Load Flux2Transformer2DModel from the local Q6_K GGUF.
      2. Load remaining components (VAE, T5, CLIP, scheduler) from HF hub
         using Flux2KleinPipeline.from_pretrained().
      3. Inject the GGUF transformer into the assembled pipeline.
      4. Move the full pipe to CUDA. Q6_K (~3.3 GB) + VAE/text encoders
         (~3 GB) = ~6 GB peak active — fits a 16 GB card with Whisper-turbo
         loaded alongside. CPU-offload is a fallback only.
      5. VAE slicing + tiling enabled for safety at high resolutions.

    Falls back to pure HF load if GGUF loading fails (e.g. no gguf package).
    """
    global _flux_pipe, _flux_device, _loaded_image_model

    spec = spec or _IMAGE_MODELS[_DEFAULT_IMAGE_MODEL]
    if _flux_pipe is not None and _loaded_image_model == spec.key:
        return _flux_pipe
    if _flux_pipe is not None:
        _unload_flux_pipeline()

    try:
        import torch
        from diffusers import Flux2KleinPipeline, Flux2Transformer2DModel
    except ImportError as e:
        raise RuntimeError(
            "diffusers ≥ 0.38 + torch required.\n"
            "  pip install torch diffusers transformers accelerate sentencepiece "
            "safetensors huggingface-hub gguf"
        ) from e

    device = _select_device()
    dtype  = torch.bfloat16   # FLUX.2-klein is trained in BF16; float16 risks NaNs

    gguf_path = _ensure_gguf(cfg, spec)

    # ── 1. GGUF transformer ────────────────────────────────────────────────
    log.info("Loading Flux2Transformer2DModel from GGUF: %s", Path(gguf_path).name)
    try:
        try:
            from diffusers import GGUFQuantizationConfig
            _gguf_cfg = GGUFQuantizationConfig(compute_dtype=dtype)
        except ImportError:
            from diffusers.quantizers.gguf import GGUFQuantizer as GGUFQuantizationConfig  # older diffusers
            _gguf_cfg = GGUFQuantizationConfig(compute_dtype=dtype)
        transformer = Flux2Transformer2DModel.from_single_file(
            gguf_path,
            quantization_config=_gguf_cfg,
            config=spec.base_repo,      # arch config; default maps to gated FLUX.2-dev
            subfolder="transformer",
            torch_dtype=dtype,
        )
        log.info("GGUF transformer loaded (GGUFQuantizationConfig).")
    except Exception as gguf_err:
        log.warning(
            "GGUF quantizer path failed (%s). "
            "Trying plain from_single_file (no quantizer)…", gguf_err
        )
        try:
            transformer = Flux2Transformer2DModel.from_single_file(
                gguf_path,
                config=spec.base_repo,      # arch config; default maps to gated FLUX.2-dev
                subfolder="transformer",
                torch_dtype=dtype,
            )
            log.info("GGUF transformer loaded (plain from_single_file).")
        except Exception as e2:
            log.warning(
                "from_single_file also failed (%s). "
                "Falling back to HF hub transformer.", e2
            )
            transformer = None   # will use pipeline's own transformer

    # ── 2. Full pipeline (VAE + text encoders + scheduler) ────────────────
    log.info("Loading Flux2KleinPipeline components from %s …", spec.base_repo)
    if transformer is not None:
        pipe = Flux2KleinPipeline.from_pretrained(
            spec.base_repo,
            transformer=transformer,
            torch_dtype=dtype,
        )
    else:
        pipe = Flux2KleinPipeline.from_pretrained(
            spec.base_repo,
            torch_dtype=dtype,
        )

    pipe.set_progress_bar_config(disable=True)

    # Guard: a parameter still on the `meta` device means its weights never
    # materialised (usually a failed transformer load). Moving such a pipe to
    # CUDA — or to CPU-offload — throws the cryptic "Cannot copy out of meta
    # tensor; no data!". Detect it here and fail loud + actionable instead.
    _meta_mods = []
    for _name in ("transformer", "vae", "text_encoder", "text_encoder_2"):
        _comp = getattr(pipe, _name, None)
        if _comp is None or not hasattr(_comp, "parameters"):
            continue
        if any(p.device.type == "meta" for p in _comp.parameters()):
            _meta_mods.append(_name)
    if _meta_mods:
        raise RuntimeError(
            "FLUX load incomplete — components with empty (meta) weights: "
            f"{', '.join(_meta_mods)}. The GGUF transformer load likely failed; "
            f"verify the GGUF file and that config repo '{spec.base_repo}' is "
            "reachable (the diffusers default 'black-forest-labs/FLUX.2-dev' is gated)."
        )

    # ── 3. Memory management ───────────────────────────────────────────────
    # Apply VRAM hard cap before first GPU allocation.
    apply_vram_cap()

    if device == "cuda":
        if _FLUX_USE_CPU_OFFLOAD:
            pipe.enable_model_cpu_offload()
            log.info("model_cpu_offload active — only active module on GPU, peak ~8 GB, no sysmem spill.")
        else:
            try:
                pipe.to("cuda")
                log.info("FLUX pipeline resident on CUDA — Q6_K, no offload.")
            except (RuntimeError, MemoryError) as e:
                log.warning(
                    "Direct CUDA load failed (%s); enabling CPU-offload fallback.", e
                )
                pipe.enable_model_cpu_offload()
        # Safety nets so 1024+ resolutions can't blow VRAM on a tight day.
        if hasattr(pipe, "vae") and pipe.vae is not None:
            for fn in ("enable_slicing", "enable_tiling"):
                try:
                    getattr(pipe.vae, fn)()
                except Exception:
                    pass
    else:
        pipe = pipe.to("cpu")

    _flux_pipe   = pipe
    _flux_device = device
    _loaded_image_model = spec.key

    # Register the unload callback. We schedule the timer only after the
    # first successful generation finishes — registering with auto-schedule
    # races with long gens (would fire mid-inference).
    register_idle_unload(
        GPUResource.FLUX,
        _unload_flux_pipeline,
        timeout_s=_FLUX_IDLE_UNLOAD_S,
        start_timer=False,
    )

    log.info("FLUX.2-klein-4B pipeline ready on %s.", device)
    return pipe


def _load_image_pipeline(cfg, model_key: str | None = None):
    spec = _image_model_spec(cfg, model_key)
    return _load_flux_pipeline(cfg, spec), spec


# ── Image generation ─────────────────────────────────────────────────────────

def _unload_flux_pipeline() -> None:
    """Completely unload the FLUX pipeline, freeing all VRAM."""
    global _flux_pipe, _flux_device, _loaded_image_model
    if _flux_pipe is None:
        return
    log.info("Unloading FLUX.2-klein-4B pipeline to free VRAM…")
    try:
        # Move all components to CPU first, then delete
        try:
            _flux_pipe.to("cpu")
        except Exception:
            pass
        del _flux_pipe
    except Exception as e:
        log.warning("Error during FLUX unload: %s", e)
    _flux_pipe = None
    _loaded_image_model = None
    _flush_gpu()
    gc.collect()
    log.info("FLUX pipeline unloaded.")


def _generate_flux2klein(
    prompt: str,
    *,
    cfg,
    image_model: str | None = None,
    width: int,
    height: int,
    steps: int,
    guidance_scale: float,
    seed: int | None,
    init_image: str | None = None,
    strength: float = 0.65,
) -> "Any":
    """Single FLUX.2-klein generation.

    Hardened against OOM:
      - Runs inside gpu_exclusive(GPUResource.FLUX) which evicts Whisper
        from GPU before we start and restores it when we finish.
      - wrap in `torch.inference_mode()` so autograd buffers never allocate
      - force `empty_cache()` + GC before AND after the call
      - On OOM: flush everything, retry once, then fail gracefully
    """
    import torch

    # Cancel any pending idle-unload since we're about to use the pipeline.
    cancel_idle_unload(GPUResource.FLUX)

    pipe, spec = _load_image_pipeline(cfg, image_model)

    # Pre-clean — any leftover allocations from a previous gen.
    _flush_gpu()

    generator = None
    if seed is not None:
        generator = torch.Generator(device="cpu").manual_seed(int(seed))

    _step_times: list[float] = []
    _t_start = time.time()

    def _on_step(pipe, step_idx, timestep, callback_kwargs):
        _step_times.append(time.time())
        elapsed = _step_times[-1] - _t_start
        eta = (elapsed / (step_idx + 1)) * (steps - step_idx - 1) if step_idx > 0 else "?"
        eta_str = f"{eta:.1f}s" if isinstance(eta, float) else eta
        log.info(
            "%s step %d/%d — elapsed %.1fs, ETA %s",
            spec.label, step_idx + 1, steps, elapsed, eta_str,
        )
        pct = int(((step_idx + 1) / steps) * 100)
        _progress_report(
            f"{spec.label}: step {step_idx + 1}/{steps} ({pct}%) - "
            f"{elapsed:.1f}s elapsed, ETA {eta_str}"
        )
        return callback_kwargs

    log.info(
        "Generating %dx%d image · %d steps · guidance %.1f%s · prompt: %s",
        width, height, steps, guidance_scale,
        f" · img2img strength={strength}" if init_image else "",
        prompt[:80],
    )
    _progress_report(f"{spec.label}: generating {width}x{height} image - {steps} steps - {prompt[:60]}...")

    # Load init image for img2img mode if provided.
    pil_init = None
    if init_image:
        from PIL import Image as _PILImage, ImageOps as _PILImageOps
        init_path = Path(init_image)
        if init_path.exists():
            with _PILImage.open(init_path) as src:
                pil_init = _PILImageOps.exif_transpose(src).convert("RGB").resize((width, height))
            log.info("img2img: using init image %s (resized to %dx%d)", init_path.name, width, height)
        else:
            log.warning("img2img: init_image not found at %s, falling back to txt2img", init_image)

    def _do_generate():
        with torch.inference_mode():
            call_kwargs: dict[str, Any] = dict(
                prompt=prompt,
                height=height,
                width=width,
                num_inference_steps=steps,
                guidance_scale=guidance_scale,
                generator=generator,
                callback_on_step_end=_on_step,
                callback_on_step_end_tensor_inputs=[],
            )
            if pil_init is not None:
                call_kwargs["image"] = pil_init
                if "strength" in inspect.signature(pipe.__call__).parameters:
                    call_kwargs["strength"] = strength
                else:
                    log.info("%s does not support img2img strength; using image conditioning only.", type(pipe).__name__)
            out = pipe(**call_kwargs)
        image = out.images[0]
        # Defensively pin a CPU-side copy so the original tensor can be GC'd.
        image.load()  # PIL.Image: forces decode of any lazy data
        # Explicitly delete the output to free intermediate tensors
        del out
        return image

    try:
        try:
            image = _do_generate()
        except (torch.cuda.OutOfMemoryError, RuntimeError) as oom_err:
            if "out of memory" in str(oom_err).lower() or isinstance(oom_err, torch.cuda.OutOfMemoryError):
                log.warning("CUDA OOM during generation — flushing and retrying…")
                _flush_gpu()
                gc.collect()
                # On retry failure, unload pipeline entirely and reload fresh
                try:
                    image = _do_generate()
                except (torch.cuda.OutOfMemoryError, RuntimeError):
                    log.warning("Second OOM — unloading pipeline and retrying with fresh load…")
                    _unload_flux_pipeline()
                    pipe, _ = _load_image_pipeline(cfg, spec.key)
                    image = _do_generate()
            else:
                raise
        return image
    finally:
        # Post-clean — drop intermediates regardless of success/failure.
        _flush_gpu()
        gc.collect()
        # Re-arm idle-unload only when a finite timeout is configured.
        # _FLUX_IDLE_UNLOAD_S = 0 means "keep pipeline loaded forever".
        if _FLUX_IDLE_UNLOAD_S > 0:
            schedule_idle_unload(GPUResource.FLUX, timeout_s=_FLUX_IDLE_UNLOAD_S)


# -- Image -> 3D (Hunyuan3D-2GP Mini Turbo) ---------------------------------

def _hy3d_models_root(cfg) -> Path:
    p = _local_models_dir(cfg) / "hunyuan3d"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _hy3d_source_dir(cfg) -> Path:
    return _local_models_dir(cfg) / f"hunyuan3d-2gp-{_HY3DGP_SOURCE_COMMIT[:8]}"


def _ensure_hy3dgp_source(cfg) -> Path:
    """Download the pinned Hunyuan3D-2GP source snapshot if absent."""
    dest = _hy3d_source_dir(cfg)
    marker = dest / "hy3dgen" / "shapegen" / "pipelines.py"
    if not marker.exists():
        models_root = _local_models_dir(cfg).resolve()
        if not str(dest.resolve(strict=False)).startswith(str(models_root)):
            raise RuntimeError(f"refusing to write Hunyuan3D source outside {models_root}")

        tmp_dir = _local_models_dir(cfg) / "_hunyuan3dgp_source_download"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        zip_path = tmp_dir / "source.zip"

        log.info("Downloading Hunyuan3D-2GP source snapshot %s", _HY3DGP_SOURCE_COMMIT[:8])
        _progress_report("Downloading Hunyuan3D-2GP runtime source...")
        try:
            urllib.request.urlretrieve(_HY3DGP_SOURCE_ZIP, zip_path)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_dir)
            candidates = [
                p for p in tmp_dir.iterdir()
                if (p / "hy3dgen" / "shapegen" / "pipelines.py").exists()
            ]
            if not candidates:
                raise RuntimeError("downloaded archive did not contain hy3dgen")
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(candidates[0]), str(dest))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    src = str(dest)
    if src not in sys.path:
        sys.path.insert(0, src)
    return dest


def _ensure_hy3d_subfolder(cfg, subfolder: str) -> Path:
    """Download only one model subfolder into data/models/hunyuan3d."""
    repo_dir = _hy3d_models_root(cfg) / _HY3D_REPO
    target = repo_dir / subfolder
    config = target / "config.yaml"
    weights = target / "model.fp16.safetensors"
    if config.exists() and weights.exists():
        return target

    log.info("Downloading %s/%s to %s", _HY3D_REPO, subfolder, repo_dir)
    _progress_report(f"Downloading {_HY3D_LABEL} files: {subfolder}...")
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(
            repo_id=_HY3D_REPO,
            allow_patterns=[
                f"{subfolder}/config.yaml",
                f"{subfolder}/model.fp16.safetensors",
            ],
            local_dir=str(repo_dir),
            max_workers=4,
        )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Failed to download {_HY3D_LABEL} subfolder '{subfolder}': {e}\n"
            f"Manual download: https://huggingface.co/{_HY3D_REPO}/tree/main/{subfolder}\n"
            f"Place files under: {target}"
        ) from e

    if not (config.exists() and weights.exists()):
        raise RuntimeError(f"Incomplete {_HY3D_LABEL} download: {target}")
    return target


def _check_hy3d_runtime() -> None:
    import importlib.util

    missing: list[str] = []
    for module, pip_name in (
        ("einops", "einops"),
        ("mmgp", "mmgp==3.2.7"),
        ("pymeshlab", "pymeshlab"),
        ("rembg", "rembg"),
    ):
        if importlib.util.find_spec(module) is None:
            missing.append(pip_name)
    if missing:
        raise RuntimeError(
            f"{_HY3D_LABEL} dependencies missing: {', '.join(missing)}. "
            "Install them in this venv, then retry."
        )


def _select_hy3d_mc_algo() -> str:
    try:
        import diso  # noqa: F401
        return "dmc"
    except Exception:
        return "mc"


def _unload_sf3d() -> None:
    """Drop the Hunyuan3D shape weights and free VRAM."""
    global _sf3d_model, _sf3d_device, _hy3d_rembg
    if _sf3d_model is None:
        return
    log.info("Unloading %s to free VRAM...", _HY3D_LABEL)
    try:
        kind, model, _mc_algo = _sf3d_model
        try:
            model.to("cpu")
        except Exception:
            pass
        del model
        del _sf3d_model
    except Exception as e:
        log.warning("Error during 3D unload: %s", e)
    _sf3d_model = None
    _sf3d_device = None
    _hy3d_rembg = None
    _flush_gpu()
    gc.collect()


def _evict_sf3d_from_gpu() -> None:
    _unload_sf3d()


def _restore_sf3d_to_gpu() -> None:
    log.info("3D restore available (will lazy-load on next 3D request)")


def _trellis2_worker_root(cfg) -> Path:
    p = _local_models_dir(cfg) / "trellis2-worker"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _trellis2_models_root(cfg) -> Path:
    p = _local_models_dir(cfg) / "trellis2"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _trellis2_source_dir(cfg) -> Path:
    return _trellis2_worker_root(cfg) / "src" / "ComfyUI-Trellis2"


def _trellis2_worker_python(cfg) -> Path:
    return _trellis2_worker_root(cfg) / "venv" / "Scripts" / "python.exe"


def _trellis2_worker_script() -> Path:
    return Path(__file__).resolve().parents[1] / "workers" / "trellis2_worker.py"


def _trellis2_setup_script(cfg) -> Path:
    return cfg.abs_path("scripts/setup_trellis2_worker.ps1")


def _ensure_trellis2_worker(cfg) -> tuple[Path, Path, Path]:
    """Ensure the isolated TRELLIS.2 Python 3.12 worker is installed."""
    py = _trellis2_worker_python(cfg)
    src = _trellis2_source_dir(cfg)
    script = _trellis2_worker_script()
    if py.exists() and (src / "trellis2" / "pipelines" / "trellis2_image_to_3d.py").exists():
        return py, src, script

    setup = _trellis2_setup_script(cfg)
    if not setup.exists():
        raise RuntimeError(f"{_TRELLIS2_LABEL} setup script missing: {setup}")

    log.info("Installing %s worker environment via %s", _TRELLIS2_LABEL, setup)
    _progress_report(f"Setting up {_TRELLIS2_LABEL} worker environment...")
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(setup),
        "-ProjectRoot",
        str(cfg.project_root),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(cfg.project_root),
        capture_output=True,
        text=True,
        timeout=_TRELLIS2_SETUP_TIMEOUT_S,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-60:])
        raise RuntimeError(f"{_TRELLIS2_LABEL} setup failed:\n{tail}")

    if not py.exists():
        raise RuntimeError(f"{_TRELLIS2_LABEL} setup completed but worker Python is missing: {py}")
    if not (src / "trellis2" / "pipelines" / "trellis2_image_to_3d.py").exists():
        raise RuntimeError(f"{_TRELLIS2_LABEL} setup completed but source is missing: {src}")
    return py, src, script


def _run_trellis2_image_to_3d(cfg, image_path: Path, out_path: Path) -> tuple[str, Path]:
    """Single image -> textured GLB via TRELLIS.2 FP8 in an isolated worker."""
    global _sf3d_device

    py, src, script = _ensure_trellis2_worker(cfg)
    if not script.exists():
        raise RuntimeError(f"{_TRELLIS2_LABEL} worker script missing: {script}")

    pipeline = _TRELLIS2_DEFAULT_PIPELINE
    if pipeline not in {"512", "1024", "1024_cascade"}:
        pipeline = "1024_cascade"
    export_mode = _TRELLIS2_EXPORT_MODE if _TRELLIS2_EXPORT_MODE in {"texture", "vertex"} else "texture"

    cmd = [
        str(py),
        str(script),
        "--input",
        str(image_path),
        "--output",
        str(out_path),
        "--models-dir",
        str(_trellis2_models_root(cfg)),
        "--trellis-src",
        str(src),
        "--seed",
        os.getenv("JARVIS_TRELLIS2_SEED", "3407"),
        "--pipeline",
        pipeline,
        "--sparse-steps",
        str(_TRELLIS2_DEFAULT_STEPS),
        "--shape-steps",
        str(_TRELLIS2_DEFAULT_STEPS),
        "--texture-steps",
        str(_TRELLIS2_TEXTURE_STEPS),
        "--max-tokens",
        str(_TRELLIS2_MAX_TOKENS),
        "--texture-size",
        str(_TRELLIS2_TEXTURE_SIZE),
        "--export-mode",
        export_mode,
    ]
    if _TRELLIS2_REMOVE_BACKGROUND:
        cmd.append("--remove-background")

    log.info("Launching %s worker (%s, %d steps, texture=%s)", _TRELLIS2_LABEL, pipeline, _TRELLIS2_DEFAULT_STEPS, export_mode)
    _progress_report(f"{_TRELLIS2_LABEL}: generating textured GLB...")
    proc = subprocess.run(
        cmd,
        cwd=str(_trellis2_worker_root(cfg)),
        capture_output=True,
        text=True,
        timeout=_TRELLIS2_WORKER_TIMEOUT_S,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    for line in combined.splitlines():
        if line.strip():
            log.info("trellis2: %s", line[:500])

    payload = None
    for line in reversed(proc.stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                payload = json.loads(stripped)
                break
            except json.JSONDecodeError:
                pass

    if proc.returncode != 0 or not payload or not payload.get("ok"):
        err = payload.get("error") if isinstance(payload, dict) else None
        tail = "\n".join(combined.splitlines()[-60:])
        raise RuntimeError(f"{_TRELLIS2_LABEL} failed: {err or tail}")

    if not out_path.exists() or out_path.stat().st_size <= 0:
        raise RuntimeError(f"{_TRELLIS2_LABEL} returned no GLB at {out_path}")

    _sf3d_device = payload.get("device", "cuda-worker")
    texture_mode = payload.get("texture", "textured")
    return f"{_TRELLIS2_KIND}-{texture_mode}", out_path


def _load_hunyuan3d(cfg):
    """Load Hunyuan3D-2GP Mini Turbo as the local image->3D backend."""
    global _sf3d_model, _sf3d_device, _hy3d_rembg
    if _sf3d_model is not None:
        return _sf3d_model, _sf3d_device

    import torch

    device = _select_device()
    if device != "cuda":
        raise RuntimeError(f"{_HY3D_LABEL} needs CUDA for the current Hunyuan3D-2GP source.")

    _check_hy3d_runtime()
    apply_vram_cap()
    _flush_gpu()

    if device == "cuda":
        try:
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cudnn.benchmark = True
            torch.set_float32_matmul_precision("high")
        except Exception:
            pass

    source_dir = _ensure_hy3dgp_source(cfg)
    os.environ["HY3DGEN_MODELS"] = str(_hy3d_models_root(cfg))
    _ensure_hy3d_subfolder(cfg, _HY3D_SHAPE_SUBFOLDER)
    _ensure_hy3d_subfolder(cfg, _HY3D_VAE_SUBFOLDER)

    try:
        from hy3dgen.rembg import BackgroundRemover  # type: ignore
        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Hunyuan3D-2GP source import failed from {source_dir}: {e}"
        ) from e

    log.info("Loading %s from %s/%s", _HY3D_LABEL, _HY3D_REPO, _HY3D_SHAPE_SUBFOLDER)
    _progress_report(f"Loading {_HY3D_LABEL} on {device}...")
    model = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        _HY3D_REPO,
        subfolder=_HY3D_SHAPE_SUBFOLDER,
        use_safetensors=True,
        device=device,
    )
    mc_algo = _select_hy3d_mc_algo()
    try:
        model.enable_flashvdm(mc_algo=mc_algo)
    except Exception as e:  # noqa: BLE001
        log.warning("FlashVDM setup with mc_algo=%s failed (%s); retrying with mc.", mc_algo, e)
        mc_algo = "mc"
        model.enable_flashvdm(mc_algo=mc_algo)

    _hy3d_rembg = BackgroundRemover()
    _sf3d_model = (_HY3D_KIND, model, mc_algo)
    _sf3d_device = device
    log.info(
        "Loaded %s on %s (steps=%d, octree=%d, chunks=%d, mc=%s).",
        _HY3D_LABEL, device, _HY3D_STEPS, _HY3D_OCTREE_RES, _HY3D_NUM_CHUNKS, mc_algo,
    )

    register_eviction(
        GPUResource.SF3D,
        evict_fn=_evict_sf3d_from_gpu,
        restore_fn=_restore_sf3d_to_gpu,
    )
    register_idle_unload(
        GPUResource.SF3D, _unload_sf3d,
        timeout_s=_HY3D_IDLE_UNLOAD_S, start_timer=False,
    )
    return _sf3d_model, _sf3d_device


def _export_image_relief_glb(img, out_path: Path) -> None:
    """Last-resort GLB: a shallow textured relief, so any image is renderable."""
    import numpy as np
    import trimesh
    from PIL import ImageOps
    from trimesh.visual.texture import TextureVisuals

    tex = img.convert("RGBA")
    max_tex = 1024
    if max(tex.size) > max_tex:
        tex.thumbnail((max_tex, max_tex))

    tex_w, tex_h = tex.size
    aspect = tex_w / max(tex_h, 1)
    grid_w = 96 if aspect >= 1 else max(32, int(96 * aspect))
    grid_h = 96 if aspect < 1 else max(32, int(96 / aspect))

    grey = ImageOps.grayscale(tex).resize((grid_w, grid_h))
    alpha = tex.getchannel("A").resize((grid_w, grid_h))
    height = np.asarray(grey, dtype=np.float32) / 255.0
    mask = np.asarray(alpha, dtype=np.float32) / 255.0

    width = 1.4 if aspect >= 1 else 1.4 * aspect
    height_world = 1.4 / aspect if aspect >= 1 else 1.4
    relief = ((height - 0.5) * 0.10 + mask * 0.035).astype(np.float32)

    vertices = []
    uvs = []
    for y in range(grid_h):
        fy = y / (grid_h - 1)
        for x in range(grid_w):
            fx = x / (grid_w - 1)
            vertices.append([
                (fx - 0.5) * width,
                (0.5 - fy) * height_world,
                float(relief[y, x]),
            ])
            uvs.append([fx, 1.0 - fy])

    faces = []
    for y in range(grid_h - 1):
        for x in range(grid_w - 1):
            a = y * grid_w + x
            b = a + 1
            c = a + grid_w
            d = c + 1
            faces.append([a, c, b])
            faces.append([b, c, d])

    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float32),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )
    mesh.visual = TextureVisuals(uv=np.asarray(uvs, dtype=np.float32), image=tex)
    mesh.metadata["extras"] = {
        "model": "image-relief-fallback",
        "reason": "Hunyuan3D returned no extractable surface",
    }
    mesh.export(str(out_path))


def _apply_projected_image_texture(mesh, img) -> None:
    """Embed a lightweight projected texture from the source image."""
    import numpy as np
    from trimesh.visual.texture import SimpleMaterial, TextureVisuals

    tex = img.convert("RGBA")
    max_tex = 1024
    if max(tex.size) > max_tex:
        tex.thumbnail((max_tex, max_tex))

    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    if vertices.size == 0:
        return

    bounds = np.asarray(mesh.bounds, dtype=np.float32)
    span = np.maximum(bounds[1] - bounds[0], 1e-6)
    u = (vertices[:, 0] - bounds[0, 0]) / span[0]
    v = 1.0 - ((vertices[:, 1] - bounds[0, 1]) / span[1])
    uv = np.column_stack([np.clip(u, 0.0, 1.0), np.clip(v, 0.0, 1.0)]).astype(np.float32)

    # TextureVisuals gives model-viewer a real embedded image texture, while
    # the UV projection keeps this pass cheap enough for the fast local path.
    mesh.visual = TextureVisuals(
        uv=uv,
        image=tex,
        material=SimpleMaterial(image=tex),
    )


def _run_hunyuan_image_to_3d(cfg, image_path: Path, out_path: Path) -> tuple[str, Path]:
    """Single image -> GLB via Hunyuan3D-2GP Mini Turbo."""
    import contextlib
    import io
    import torch
    from PIL import Image

    (kind, model, mc_algo), device = _load_hunyuan3d(cfg)

    with Image.open(image_path) as src:
        raw_img = src.convert("RGB")

    img = raw_img
    try:
        if _hy3d_rembg is not None:
            img = _hy3d_rembg(raw_img)
    except Exception as e:  # noqa: BLE001
        log.warning("%s background removal skipped (%s); using raw image.", _HY3D_LABEL, e)

    image_variants = [("rembg", img)]
    if img is not raw_img:
        image_variants.append(("raw", raw_img))
    mesh_algos = [mc_algo] if mc_algo == "mc" else [mc_algo, "mc"]
    attempts: list[str] = []

    def _sample_latents(input_img, seed: int):
        generator = torch.Generator(device=device).manual_seed(seed)
        return model(
            image=input_img,
            num_inference_steps=_HY3D_STEPS,
            guidance_scale=_HY3D_GUIDANCE,
            generator=generator,
            octree_resolution=_HY3D_OCTREE_RES,
            num_chunks=_HY3D_NUM_CHUNKS,
            output_type="latent",
            mc_algo=None,
            enable_pbar=False,
        )

    _progress_report(f"{_HY3D_LABEL}: generating mesh...")
    mesh = None
    used = {"variant": "", "seed": 0, "mc_algo": mc_algo, "mc_level": 0.0}
    with torch.inference_mode():
        for variant_name, input_img in image_variants:
            for seed in _HY3D_RETRY_SEEDS:
                _progress_report(
                    f"{_HY3D_LABEL}: sampling {variant_name} seed {seed}..."
                )
                latents = _sample_latents(input_img, seed)
                for level in _HY3D_MC_LEVELS:
                    for algo in mesh_algos:
                        try:
                            export_stderr = io.StringIO()
                            with contextlib.redirect_stderr(export_stderr):
                                meshes = model._export(
                                    latents,
                                    output_type="trimesh",
                                    box_v=1.01,
                                    mc_level=level,
                                    num_chunks=_HY3D_NUM_CHUNKS,
                                    octree_resolution=_HY3D_OCTREE_RES,
                                    mc_algo=algo,
                                    enable_pbar=False,
                                )
                            mesh = meshes[0] if meshes else None
                            if mesh is None and export_stderr.getvalue():
                                log.debug(
                                    "%s no-surface export detail: %s",
                                    _HY3D_LABEL,
                                    export_stderr.getvalue().splitlines()[-1],
                                )
                        except Exception as e:  # noqa: BLE001
                            attempts.append(f"{variant_name}/seed={seed}/{algo}/{level:g}: {e}")
                            mesh = None
                        if mesh is not None:
                            used = {
                                "variant": variant_name,
                                "seed": seed,
                                "mc_algo": algo,
                                "mc_level": level,
                            }
                            break
                    if mesh is not None:
                        break
                if mesh is not None:
                    break
                attempts.append(f"{variant_name}/seed={seed}: no extractable surface")
            if mesh is not None:
                break

    if mesh is None:
        log.warning(
            "%s returned no mesh after retries; exporting image relief fallback. Attempts: %s",
            _HY3D_LABEL,
            " | ".join(attempts[-8:]),
        )
        _export_image_relief_glb(raw_img, out_path)
        return f"{kind}-relief-fallback", out_path

    try:
        mesh.metadata["extras"] = {
            "model": f"{_HY3D_REPO}/{_HY3D_SHAPE_SUBFOLDER}",
            "steps": _HY3D_STEPS,
            "guidance_scale": _HY3D_GUIDANCE,
            "octree_resolution": _HY3D_OCTREE_RES,
            "num_chunks": _HY3D_NUM_CHUNKS,
            "mc_algo": used["mc_algo"],
            "mc_level": used["mc_level"],
            "seed": used["seed"],
            "input_variant": used["variant"],
        }
    except Exception:
        pass
    if os.getenv("JARVIS_HY3D_PROJECT_TEXTURE", "0").strip().lower() in {"1", "true", "yes"}:
        try:
            texture_img = img if used["variant"] == "rembg" else raw_img
            _apply_projected_image_texture(mesh, texture_img)
            mesh.metadata.setdefault("extras", {})["texture"] = "projected-source-image"
        except Exception as e:  # noqa: BLE001
            log.warning("Projected texture skipped for %s: %s", out_path.name, e)
    mesh.export(str(out_path))
    return kind, out_path


def _run_image_to_3d(cfg, image_path: Path, out_path: Path) -> tuple[str, Path]:
    backend = os.getenv("JARVIS_3D_BACKEND", "trellis2-fp8").strip().lower()
    if backend in {"hunyuan", "hy3d", "hunyuan3d", "hunyuan3d-2gp"}:
        return _run_hunyuan_image_to_3d(cfg, image_path, out_path)
    return _run_trellis2_image_to_3d(cfg, image_path, out_path)


# ── Plugin registration ──────────────────────────────────────────────────────

def register(registry):
    cfg = registry.cfg

    @tool(
        name="image_generate",
        description=(
            "★ PREFERRED for any 'generate/create/make/draw/render/paint/design' "
            "image request. Runs FLUX.2-klein-4B locally and pushes the result "
            "to the Media Bay as an inline image card. NEVER suggest the user "
            "'go to a website for image generation' — this tool IS the service."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "prompt":         {"type": "string"},
                "width":          {"type": "integer", "default": 1024},
                "height":         {"type": "integer", "default": 1024},
                "steps":          {"type": "integer",  "default": 0,
                                   "description": "0 or omitted uses the model default (4)."},
                "guidance_scale": {"type": "number",   "default": -1,
                                   "description": "-1 or omitted uses the model default (4.0)."},
                "seed":           {"type": "integer",  "description": "Optional reproducibility seed."},
                "init_image":     {"type": "string",   "description": "Optional path to an init image for img2img mode."},
                "strength":       {"type": "number",   "default": 0.65,
                                   "description": "img2img strength (0.0=keep original, 1.0=ignore original). Only used with init_image."},
            },
            "required": ["prompt"],
        },
        preview=lambda a: f"image_generate: {a.get('prompt','')[:80]}",
    )
    async def image_generate(
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        steps: int | None = None,
        guidance_scale: float | None = None,
        seed: int | None = None,
        init_image: str | None = None,
        strength: float = 0.65,
    ) -> str:
        if not prompt.strip():
            return "empty prompt"

        selected_spec = _image_model_spec(cfg)
        if steps is None or int(steps) <= 0:
            steps = selected_spec.default_steps
        if guidance_scale is None or float(guidance_scale) < 0:
            guidance_scale = selected_spec.default_guidance

        # Resolve init_image path if it's an API URL.
        resolved_init = None
        if init_image:
            p_str = init_image.strip()
            if p_str.startswith("/api/files/"):
                rel = p_str[len("/api/files/"):]
                resolved_init = str(cfg.abs_path("data/" + rel))
            else:
                resolved_init = p_str

        if resolved_init:
            try:
                from PIL import Image as _PILImage, ImageOps as _PILImageOps
                init_path = Path(resolved_init)
                if init_path.exists():
                    with _PILImage.open(init_path) as probe:
                        src_w, src_h = _PILImageOps.exif_transpose(probe).size
                    new_width, new_height = _fit_size_to_aspect(src_w, src_h, width, height)
                    if (new_width, new_height) != (width, height):
                        log.info(
                            "img2img: preserving input aspect ratio %dx%d -> %dx%d",
                            src_w, src_h, new_width, new_height,
                        )
                    width, height = new_width, new_height
            except Exception as e:  # noqa: BLE001
                log.warning("img2img: could not read init image aspect ratio (%s)", e)

        loop = asyncio.get_running_loop()
        t0   = time.time()
        # The VRAM manager's exclusive lock evicts Whisper from GPU before
        # generation and restores it after. This prevents the two models
        # from competing for the same 16 GB of VRAM.
        ctx = await gpu_exclusive_async(GPUResource.FLUX)
        async with ctx:
            try:
                img = await loop.run_in_executor(
                    None,
                    lambda: _generate_flux2klein(
                        prompt,
                        cfg=cfg,
                        image_model=selected_spec.key,
                        width=width,
                        height=height,
                        steps=steps,
                        guidance_scale=guidance_scale,
                        seed=seed,
                        init_image=resolved_init,
                        strength=strength,
                    ),
                )
            except RuntimeError as e:
                _flush_gpu()
                return f"image gen failed: {e}"
            except Exception as e:  # noqa: BLE001
                log.exception("image gen unexpected error")
                _flush_gpu()
                return f"image gen error: {type(e).__name__}: {e}"
            dt = time.time() - t0

            out_dir = _images_dir(cfg)
            fname   = f"{selected_spec.key}-{int(time.time())}-{_short_hash(prompt)}.png"
            path    = out_dir / fname
            try:
                img.save(path)
            except Exception as e:  # noqa: BLE001
                log.exception("PIL save failed for %s", fname)
                _flush_gpu()
                return f"image save failed: {e}"
            finally:
                # Drop the PIL handle ASAP; large images keep ~12 MB each in RAM.
                try:
                    img.close()
                except Exception:
                    pass
                del img
                _flush_gpu()

            url = f"/api/files/generated/images/{fname}"
            log.info("image_generate OK (%.1fs) → %s", dt, path.name)
        return _emit_media(
            "image",
            [{
                "url":       url,
                "thumbnail": url,
                "title":     prompt[:80],
                "snippet":   f"{width}x{height} | {steps} steps | {dt:.1f}s | {selected_spec.label} ({_flux_device})",
                "source":    f"local | {selected_spec.label}",
            }],
            f"Generated: {prompt[:120]}",
        )

    @tool(
        name="image_to_3d",
        description=(
            "★ Convert ANY image (a generated image, an uploaded/attached photo, "
            "or a Media Bay image URL) into an interactive textured 3D GLB model using "
            "TRELLIS.2 FP8 (local, ungated public weights). Use this whenever the user says "
            "'turn this into 3D', 'make a 3D model of this', etc. The result "
            "renders inline in the Media Bay with an interactive 3D viewer."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "image_path": {"type": "string"},
                "title":      {"type": "string", "default": ""},
            },
            "required": ["image_path"],
        },
        preview=lambda a: f"image_to_3d: {a.get('image_path','')}",
    )
    async def image_to_3d(image_path: str, title: str = "") -> str:
        p_str = image_path.strip()
        if p_str.startswith("/api/files/"):
            rel = p_str[len("/api/files/"):]
            p   = cfg.abs_path("data/" + rel)
        else:
            p = Path(p_str)
            if not p.is_absolute():
                p = cfg.abs_path(str(p))
        if not p.exists():
            return f"image not found: {p}"

        out_dir  = _models_dir(cfg)
        out_name = f"model-{int(time.time())}-{_short_hash(p.name)}.glb"
        out_path = out_dir / out_name

        loop = asyncio.get_running_loop()
        t0   = time.time()
        cancel_idle_unload(GPUResource.SF3D)
        ctx = await gpu_exclusive_async(GPUResource.SF3D)
        async with ctx:
            try:
                kind, _ = await loop.run_in_executor(None, lambda: _run_image_to_3d(cfg, p, out_path))
            except RuntimeError as e:
                _flush_gpu()
                return f"3D gen failed: {e}"
            except Exception as e:  # noqa: BLE001
                log.exception("3D gen unexpected error")
                _flush_gpu()
                return f"3D gen error: {type(e).__name__}: {e}"
            finally:
                _flush_gpu()
                gc.collect()
                schedule_idle_unload(GPUResource.SF3D, timeout_s=_HY3D_IDLE_UNLOAD_S)
        dt  = time.time() - t0
        url = f"/api/files/generated/models3d/{out_name}"
        log.info("image_to_3d OK (%.1fs, %s) → %s", dt, kind, out_path.name)
        return _emit_media(
            "model3d",
            [{
                "url":       url,
                "thumbnail": (f"/api/files/{p_str.replace('/api/files/','')}"
                              if p_str.startswith("/api/files/") else ""),
                "title":     title or f"3D from {p.name}",
                "snippet":   f"{kind} · {dt:.1f}s · {_sf3d_device}",
                "source":    "local · " + kind,
            }],
            f"3D model generated ({kind}, {dt:.1f}s).",
        )

    @tool(
        name="text_to_3d",
        description=(
            "Generate a 3D model from a text prompt. Pipeline: image_generate "
            "(FLUX.2-klein) -> image_to_3d (TRELLIS.2 FP8 textured). Returns an inline "
            "3D viewer card in the Media Bay."
        ),
        permission=Permission.SAFE,
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "steps":  {"type": "integer", "default": 4},
            },
            "required": ["prompt"],
        },
        preview=lambda a: f"text_to_3d: {a.get('prompt','')[:80]}",
    )
    async def text_to_3d(prompt: str, steps: int = 4) -> str:
        intermediate = await image_generate(prompt, steps=steps)
        if not intermediate.startswith(MEDIA_PREFIX):
            return intermediate
        try:
            payload = json.loads(intermediate[len(MEDIA_PREFIX):])
            img_url = payload["items"][0]["url"]
        except Exception:
            return "text_to_3d: could not parse intermediate image"
        return await image_to_3d(img_url, title=prompt[:80])

    registry.add_pending("media_generation")
    registry.register_plugin(PluginInfo(
        name="media_generation",
        description="Selectable local image generation + TRELLIS.2 FP8 textured 3D generation.",
        permissions_needed=[Permission.SAFE],
    ))
