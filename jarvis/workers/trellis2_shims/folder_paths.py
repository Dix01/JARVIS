"""Minimal ComfyUI folder_paths shim for the TRELLIS.2 standalone worker."""
from __future__ import annotations

import os

models_dir = os.environ.get("TRELLIS2_MODELS_DIR", os.getcwd())
