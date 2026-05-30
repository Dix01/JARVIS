"""FastAPI server that exposes the orchestrator over REST + WebSocket and
optionally serves the built web frontend.

REST endpoints:
  GET  /api/health        — server up + basic info
  GET  /api/stats         — live system + process telemetry
  GET  /api/tools         — registered tools (name, description, permission)
  GET  /api/plugins       — registered plugins
  GET  /api/agents        — registered agents
  GET  /api/memory/*      — read memory (prefs, notes, paths, tools, search)
  POST /api/cleanslate    — DANGEROUS: wipe conversation history
  GET  /api/persona       — current persona text
  POST /api/persona       — set persona

WebSocket:
  /ws                     — bi-directional chat / events stream
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import Config
from ..core.memory import Memory
from ..core.orchestrator import Orchestrator
from ..plugins.registry import PluginRegistry
from . import routes, ws

log = logging.getLogger("jarvis.server")


def _silence_proactor_reset(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """Suppress benign Windows Proactor 'connection forcibly closed' tracebacks.

    Python 3.13 + asyncio Proactor logs a noisy ConnectionResetError whenever
    a remote (browser tab, websocket) drops the socket mid-write. The
    underlying handler is `_ProactorBasePipeTransport._call_connection_lost`.
    These are harmless — silence to keep the JARVIS console readable.
    """
    exc = context.get("exception")
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return
    msg = context.get("message", "")
    if "_call_connection_lost" in msg or "forcibly closed" in msg:
        return
    # Anything else → default handler.
    loop.default_exception_handler(context)


def create_app(
    cfg: Config,
    orchestrator: Orchestrator,
    registry: PluginRegistry,
    memory: Memory,
    agents,
    web_dist: Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Install the noise filter on the running loop.
        try:
            asyncio.get_running_loop().set_exception_handler(_silence_proactor_reset)
        except Exception:  # noqa: BLE001
            pass
        # Wire the SSE log handler — must happen after the event loop is running.
        routes.install_log_handler()

        # Apply VRAM hard cap before any GPU models load.
        from ..core.vram_manager import apply_vram_cap
        apply_vram_cap()

        log.info("server up — model=%s tools=%d agents=%d",
                 cfg.model.model, len(registry.all_tools()), len(agents.list()))

        # ── Preload models in background so first request is instant. ──
        # ORDER MATTERS for GPU memory: FLUX (~6–10 GB peak with text
        # encoders) loads FIRST so it gets a clean allocator. Whisper-turbo
        # (~1.5 GB) loads after — much less likely to OOM on a 16 GB card.
        async def _preload() -> None:
            loop = asyncio.get_running_loop()
            log.info("preloading models in background…")
            # FLUX first so it lands in clean VRAM.
            try:
                from ..plugins import media_generation as _mg
                if getattr(_mg, "_FLUX_PRELOAD_AT_STARTUP", False):
                    log.info("Pre-warming FLUX.2-klein-4B pipeline…")
                    await loop.run_in_executor(None, _mg._load_flux_pipeline, cfg)
                    log.info("✓ FLUX preloaded")
            except Exception as e:  # noqa: BLE001
                log.warning("FLUX preload failed: %s", e)
            try:
                await loop.run_in_executor(None, routes._get_whisper_model)
                log.info("✓ Whisper preloaded")
            except Exception as e:  # noqa: BLE001
                log.warning("Whisper preload failed: %s", e)
            try:
                if routes._should_try_piper(cfg):
                    await loop.run_in_executor(None, routes._synthesize_with_piper, "ready", cfg)
                    log.info("✓ Piper preloaded")
            except Exception as e:  # noqa: BLE001
                log.warning("Piper preload failed: %s", e)
            try:
                import edge_tts  # noqa: F401
                log.info("✓ Edge-TTS available")
            except Exception as e:  # noqa: BLE001
                log.warning("Edge-TTS unavailable: %s", e)
            log.info("model preload complete.")

        preload_task = asyncio.create_task(_preload())

        yield

        preload_task.cancel()
        try:
            await preload_task
        except (asyncio.CancelledError, Exception):
            pass
        await orchestrator.brain.aclose()

    app = FastAPI(title="JARVIS", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Stash services on app.state so routes/ws can read them
    app.state.cfg = cfg
    app.state.orchestrator = orchestrator
    app.state.registry = registry
    app.state.memory = memory
    app.state.agents = agents

    app.include_router(routes.router, prefix="/api")
    app.add_api_websocket_route("/ws", ws.websocket_endpoint)

    if web_dist and web_dist.exists():
        # Mount built frontend assets
        assets_dir = web_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        index = web_dist / "index.html"

        @app.get("/")
        async def index_route():
            if index.exists():
                return FileResponse(index)
            return JSONResponse({"error": "frontend not built. run: cd web && npm install && npm run build"})

        # SPA fallback — any non-/api/* path returns index.html
        @app.get("/{full_path:path}")
        async def spa(full_path: str):
            target = web_dist / full_path
            if target.is_file():
                return FileResponse(target)
            return FileResponse(index) if index.exists() else JSONResponse({"error": "not found"}, status_code=404)
    else:
        @app.get("/")
        async def no_frontend():
            return {
                "service": "JARVIS",
                "status": "online",
                "frontend": "not built — run: cd web && npm install && npm run dev",
                "websocket": "/ws",
                "api": "/api",
            }

    return app
