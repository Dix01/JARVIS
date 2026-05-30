"""Minimal ComfyUI utils shim required by ComfyUI-Trellis2."""
from __future__ import annotations


class ProgressBar:
    def __init__(self, total: int = 0):
        self.total = max(0, int(total or 0))
        self.current = 0
        if self.total:
            print(f"progress 0/{self.total}", flush=True)

    def update(self, amount: int = 1):
        self.current += int(amount or 1)
        if self.total:
            self.current = min(self.current, self.total)
            print(f"progress {self.current}/{self.total}", flush=True)

    def update_absolute(self, value: int, total: int | None = None, preview=None):
        if total is not None:
            self.total = max(0, int(total or 0))
        self.current = int(value or 0)
        if self.total:
            self.current = min(self.current, self.total)
            print(f"progress {self.current}/{self.total}", flush=True)


def common_upscale(*args, **kwargs):
    raise NotImplementedError("common_upscale is not available in the Jarvis TRELLIS.2 worker shim")


def load_torch_file(*args, **kwargs):
    raise NotImplementedError("load_torch_file is not available in the Jarvis TRELLIS.2 worker shim")
