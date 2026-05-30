"""Entry point: load config, wire services, launch FastAPI server."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Force UTF-8 stdout on Windows so the banner renders without cp1252 errors.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

# Cut PyTorch CUDA fragmentation. MUST be set before torch is first imported
# anywhere in the process — heavy models (FLUX, Whisper, SF3D) cycle in/out
# of VRAM and the default allocator fragments enough to OOM at 16 GB.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

from .agents import build_default_registry
from .config import load_config
from .core.brain import LLMBrain
from .core.hooks import HookRegistry
from .core.logger import ActionLog, setup_logging
from .core.memory import Memory
from .core.orchestrator import Orchestrator
from .core.permissions import PermissionManager
from .plugins.registry import PluginRegistry

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = PROJECT_ROOT / "web" / "dist"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="jarvis", description="JARVIS — local AI desktop assistant")
    p.add_argument("--config", "-c", help="Path to config.yaml", default=None)
    p.add_argument("--host", default="127.0.0.1", help="HTTP bind host (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=7341, help="HTTP bind port (default 7341)")
    p.add_argument("--check", action="store_true", help="Boot, log diagnostics, then exit (no server)")
    p.add_argument("--no-browser", action="store_true", help="Don't auto-open the browser")
    return p.parse_args(argv)


def build_services(cfg_path: str | None):
    cfg = load_config(cfg_path)
    logger = setup_logging(cfg)
    actions = ActionLog(cfg)
    memory = Memory(cfg)
    permissions = PermissionManager(cfg)
    brain = LLMBrain(cfg)

    # ULTIMATE: semantic long-term memory. Flag-gated and fully optional —
    # any failure (missing numpy, no embeddings endpoint) degrades to the
    # baseline keyword memory without breaking boot.
    semantic = None
    _ult = getattr(cfg, "ultimate", None)
    if _ult is not None and _ult.enabled and _ult.semantic_memory:
        try:
            from .core.embeddings import EmbeddingClient
            from .core.semantic_memory import SemanticMemory
            semantic = SemanticMemory(cfg, EmbeddingClient(cfg))
            logger.info("semantic memory online — %d facts stored", semantic.count())
        except Exception as e:  # noqa: BLE001
            logger.warning("semantic memory disabled: %s", e)
            semantic = None

    services = {
        "cfg": cfg,
        "memory": memory,
        "permissions": permissions,
        "actions": actions,
        "brain": brain,
        "semantic": semantic,
    }
    registry = PluginRegistry(cfg, services=services)
    registry.load_all()

    hooks = HookRegistry()
    orchestrator = Orchestrator(
        cfg=cfg,
        brain=brain,
        registry=registry,
        memory=memory,
        permissions=permissions,
        actions=actions,
        hooks=hooks,
        semantic=semantic,
    )
    # Expose the orchestrator back to plugins (specifically the parallel_tasks
    # swarm tool, which fans calls out through orchestrator._invoke_tool).
    registry.services["orchestrator"] = orchestrator
    agents = build_default_registry(cfg)

    return cfg, logger, brain, registry, memory, permissions, actions, orchestrator, agents


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg, logger, brain, registry, memory, perms, actions, orch, agents = build_services(args.config)

    logger.info("JARVIS booting — provider=%s model=%s endpoint=%s",
                cfg.model.provider, cfg.model.model, cfg.model.endpoint)
    logger.info("plugins=%s tools=%s agents=%s",
                len(registry.plugins()), len(registry.all_tools()), len(agents.list()))

    if args.check:
        print(f"[ok] config loaded from {cfg.project_root}")
        print(f"[ok] plugins: {[p.name for p in registry.plugins()]}")
        print(f"[ok] tools  : {len(registry.all_tools())}")
        print(f"[ok] agents : {agents.names()}")
        print(f"[ok] model  : {cfg.model.provider} :: {cfg.model.model} @ {cfg.model.endpoint}")
        print(f"[ok] memory : {memory.path}")
        print(f"[ok] web dist exists: {WEB_DIST.exists()}")
        return 0

    # Import here so --check works even if FastAPI/uvicorn not installed yet
    import uvicorn
    from .server.app import create_app

    app = create_app(
        cfg=cfg,
        orchestrator=orch,
        registry=registry,
        memory=memory,
        agents=agents,
        web_dist=WEB_DIST if WEB_DIST.exists() else None,
    )

    url = f"http://{args.host}:{args.port}"
    print()
    print("  ╔════════════════════════════════════════════════════════╗")
    print(f"  ║   J . A . R . V . I . S .   online at  {url:<14}     ║")
    print("  ╚════════════════════════════════════════════════════════╝")
    print(f"   model     : {cfg.model.provider} :: {cfg.model.model}")
    print(f"   endpoint  : {cfg.model.endpoint}")
    print(f"   frontend  : {'built (served)' if WEB_DIST.exists() else 'dev mode (run `cd web && npm run dev`)'}")
    print(f"   ws        : ws://{args.host}:{args.port}/ws")
    print()

    if not args.no_browser and WEB_DIST.exists():
        import threading
        import time
        import webbrowser

        def _open():
            time.sleep(0.8)
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
