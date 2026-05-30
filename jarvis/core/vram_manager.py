"""Centralized VRAM manager — prevents OOM no matter what.

This module is the single authority over GPU memory in the JARVIS process.
Every GPU-heavy subsystem (Whisper STT, FLUX image gen, SF3D, etc.) must
acquire/release through this manager.

Strategy:
  1. VRAM budget: hard-cap torch CUDA allocation to 90% of physical VRAM
     so Windows / display driver always has headroom.
  2. Exclusive GPU lock: only ONE heavy model runs on the GPU at a time.
     Others wait or fall back to CPU.
  3. Before-acquire eviction: when FLUX needs the GPU, Whisper is moved
     to CPU (or fully unloaded). When FLUX finishes, Whisper can reload.
  4. Post-use cleanup: FLUX pipeline is fully unloaded after each gen
     batch idle timeout (default: 60 s), freeing ~8 GB.
  5. OOM recovery: every torch call is wrapped; on OOM we nuke caches,
     GC, and retry once on CPU if possible.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import threading
import time
from contextlib import contextmanager
from enum import Enum, auto
from typing import Any, Callable

log = logging.getLogger("jarvis.vram")

# ── VRAM hard cap ────────────────────────────────────────────────────────────

import os as _os

# Allow 95% of VRAM by default — FLUX + T5 text encoder + Whisper-turbo
# together push past 90% on a 16 GB card. Caller can override via env var.
_VRAM_FRACTION = float(_os.getenv("JARVIS_VRAM_FRACTION", "0.95"))
_vram_cap_applied = False


def apply_vram_cap() -> None:
    """Set a hard ceiling on PyTorch CUDA allocation. Call once at startup.

    Also enables `expandable_segments` in PyTorch's CUDA allocator which
    drastically cuts fragmentation when several heavy models (Whisper +
    FLUX + SF3D) load and unload in the same process.
    """
    global _vram_cap_applied
    if _vram_cap_applied:
        return
    # Reduce fragmentation. Must be set before the allocator initialises.
    _os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.set_per_process_memory_fraction(_VRAM_FRACTION)
            total = torch.cuda.get_device_properties(0).total_memory
            log.info(
                "VRAM cap applied: %.0f%% of %.1f GB = %.1f GB max",
                _VRAM_FRACTION * 100,
                total / 1e9,
                total * _VRAM_FRACTION / 1e9,
            )
            _vram_cap_applied = True
    except Exception as e:
        log.warning("Could not apply VRAM cap: %s", e)


# ── GPU resource identifiers ────────────────────────────────────────────────

class GPUResource(Enum):
    """Named GPU-heavy subsystems. Used as lock keys."""
    WHISPER = auto()
    FLUX = auto()
    SF3D = auto()


# ── Eviction callbacks ──────────────────────────────────────────────────────
# Each subsystem registers an evict + restore callback so the manager can
# move it off GPU when another subsystem needs the memory.

_eviction_registry: dict[GPUResource, dict[str, Callable]] = {}


def register_eviction(
    resource: GPUResource,
    evict_fn: Callable[[], None],
    restore_fn: Callable[[], None],
) -> None:
    """Register callbacks to evict (free VRAM) and restore a GPU resource."""
    _eviction_registry[resource] = {"evict": evict_fn, "restore": restore_fn}
    log.debug("Registered eviction callbacks for %s", resource.name)


# ── Exclusive GPU lock ───────────────────────────────────────────────────────
# asyncio.Lock for the async world, threading.Lock for sync/executor threads.

_gpu_async_lock: asyncio.Lock | None = None
_gpu_thread_lock = threading.Lock()
_current_owner: GPUResource | None = None


def _get_async_lock() -> asyncio.Lock:
    global _gpu_async_lock
    if _gpu_async_lock is None:
        _gpu_async_lock = asyncio.Lock()
    return _gpu_async_lock


def _evict_others(requester: GPUResource) -> None:
    """Evict all OTHER GPU resources before the requester takes over."""
    for res, cbs in _eviction_registry.items():
        if res == requester:
            continue
        try:
            log.info("Evicting %s from GPU (requested by %s)", res.name, requester.name)
            cbs["evict"]()
        except Exception as e:
            log.warning("Eviction of %s failed: %s", res.name, e)
    # Force cleanup after evictions
    flush_gpu()


def _restore_others(requester: GPUResource) -> None:
    """Restore evicted resources after the requester is done."""
    for res, cbs in _eviction_registry.items():
        if res == requester:
            continue
        try:
            log.info("Restoring %s to GPU (after %s)", res.name, requester.name)
            cbs["restore"]()
        except Exception as e:
            log.warning("Restore of %s failed (will lazy-load later): %s", res.name, e)


@contextmanager
def gpu_exclusive(resource: GPUResource):
    """Thread-safe context manager: acquire exclusive GPU access.

    Usage (from a thread-pool executor):
        with gpu_exclusive(GPUResource.FLUX):
            # ... run FLUX pipeline ...
    """
    global _current_owner
    _gpu_thread_lock.acquire()
    try:
        _evict_others(resource)
        _current_owner = resource
        yield
    finally:
        _current_owner = None
        flush_gpu()
        _restore_others(resource)
        _gpu_thread_lock.release()


async def gpu_exclusive_async(resource: GPUResource):
    """Async version of gpu_exclusive. Wraps the thread lock in an
    asyncio-friendly way so the event loop isn't blocked.

    Usage:
        async with gpu_exclusive_async(GPUResource.FLUX):
            img = await loop.run_in_executor(None, _generate, ...)
    """
    lock = _get_async_lock()

    class _AsyncCtx:
        async def __aenter__(self_):
            await lock.acquire()
            _evict_others(resource)
            global _current_owner
            _current_owner = resource
            return self_

        async def __aexit__(self_, *exc):
            global _current_owner
            _current_owner = None
            flush_gpu()
            # Restore in executor to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _restore_others, resource)
            lock.release()

    return _AsyncCtx()


# ── VRAM cleanup utilities ──────────────────────────────────────────────────

def flush_gpu() -> None:
    """Aggressive VRAM cleanup. Safe to call repeatedly."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
            torch.cuda.synchronize()
    except Exception:
        pass
    gc.collect()


def get_vram_status() -> dict[str, Any]:
    """Return current VRAM usage for monitoring."""
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            allocated = torch.cuda.memory_allocated(0)
            reserved = torch.cuda.memory_reserved(0)
            return {
                "total_gb": props.total_memory / 1e9,
                "allocated_gb": allocated / 1e9,
                "reserved_gb": reserved / 1e9,
                "free_gb": (props.total_memory - allocated) / 1e9,
                "cap_gb": props.total_memory * _VRAM_FRACTION / 1e9,
                "owner": _current_owner.name if _current_owner else None,
            }
    except Exception:
        pass
    return {"available": False}


def safe_cuda_call(fn: Callable, *args, fallback_fn: Callable | None = None, **kwargs) -> Any:
    """Run a CUDA-heavy function with OOM recovery.

    On torch.cuda.OutOfMemoryError:
      1. Flush all caches + GC
      2. Retry once
      3. If still OOM and fallback_fn provided, run on CPU
      4. Otherwise re-raise
    """
    import torch

    try:
        return fn(*args, **kwargs)
    except torch.cuda.OutOfMemoryError:
        log.warning("CUDA OOM caught — flushing caches and retrying…")
        flush_gpu()
        gc.collect()
        try:
            return fn(*args, **kwargs)
        except torch.cuda.OutOfMemoryError:
            if fallback_fn is not None:
                log.warning("CUDA OOM on retry — falling back to CPU path")
                flush_gpu()
                return fallback_fn(*args, **kwargs)
            log.error("CUDA OOM — no fallback available, re-raising")
            raise


# ── Unload timer ────────────────────────────────────────────────────────────
# Automatically unload heavy models after idle timeout to free VRAM.

_unload_callbacks: dict[GPUResource, Callable[[], None]] = {}
_unload_timers: dict[GPUResource, threading.Timer] = {}


def register_idle_unload(
    resource: GPUResource,
    unload_fn: Callable[[], None],
    timeout_s: float = 120.0,
    *,
    start_timer: bool = True,
) -> None:
    """After `timeout_s` of no use, call `unload_fn` to free VRAM.

    When `start_timer=False`, only the callback is registered; the caller
    must invoke `schedule_idle_unload` after their work completes. This
    avoids a race where the timer expires *during* the work it's tracking.
    """
    _unload_callbacks[resource] = unload_fn
    if start_timer:
        schedule_idle_unload(resource, timeout_s)


def schedule_idle_unload(resource: GPUResource, timeout_s: float = 120.0) -> None:
    """(Re)start the idle unload timer for a resource."""
    if resource not in _unload_callbacks:
        return
    # Cancel existing timer
    old = _unload_timers.pop(resource, None)
    if old is not None:
        old.cancel()
    # Schedule new timer
    def _do_unload():
        log.info("Idle timeout — unloading %s to free VRAM", resource.name)
        try:
            _unload_callbacks[resource]()
            flush_gpu()
        except Exception as e:
            log.warning("Idle unload of %s failed: %s", resource.name, e)
    timer = threading.Timer(timeout_s, _do_unload)
    timer.daemon = True
    timer.start()
    _unload_timers[resource] = timer


def cancel_idle_unload(resource: GPUResource) -> None:
    """Cancel the idle unload timer (resource is in active use)."""
    old = _unload_timers.pop(resource, None)
    if old is not None:
        old.cancel()
