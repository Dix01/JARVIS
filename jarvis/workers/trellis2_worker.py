"""Standalone TRELLIS.2 FP8 image-to-3D worker.

The main Jarvis process runs on Python 3.13. ComfyUI-Trellis2 ships tested
Windows wheels for Python 3.12 + Torch 2.8, so this worker is intentionally
isolated in data/models/trellis2-worker/venv and invoked as a subprocess.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


FP8_REPO = "visualbruno/TRELLIS.2-4B-FP8"
DINO_REPO = "404-Gen/dinov3-vitl16-pretrain-lvd1689m"
SPARSE_DECODER_REPO = "microsoft/TRELLIS-image-large"
KIND = "trellis2-fp8-textured"

FP8_PATTERNS = [
    "pipeline_fp8.json",
    "ckpts_fp8/ss_flow_img_dit_1_3B_64_fp8.json",
    "ckpts_fp8/ss_flow_img_dit_1_3B_64_fp8.safetensors",
    "ckpts_fp8/shape_dec_next_dc_f16c32_fp8.json",
    "ckpts_fp8/shape_dec_next_dc_f16c32_fp8.safetensors",
    "ckpts_fp8/slat_flow_img2shape_dit_1_3B_512_fp8.json",
    "ckpts_fp8/slat_flow_img2shape_dit_1_3B_512_fp8.safetensors",
    "ckpts_fp8/slat_flow_img2shape_dit_1_3B_1024_fp8.json",
    "ckpts_fp8/slat_flow_img2shape_dit_1_3B_1024_fp8.safetensors",
    "ckpts_fp8/tex_dec_next_dc_f16c32_fp8.json",
    "ckpts_fp8/tex_dec_next_dc_f16c32_fp8.safetensors",
    "ckpts_fp8/slat_flow_imgshape2tex_dit_1_3B_512_fp8.json",
    "ckpts_fp8/slat_flow_imgshape2tex_dit_1_3B_512_fp8.safetensors",
    "ckpts_fp8/slat_flow_imgshape2tex_dit_1_3B_1024_fp8.json",
    "ckpts_fp8/slat_flow_imgshape2tex_dit_1_3B_1024_fp8.safetensors",
]
SPARSE_DECODER_PATTERNS = [
    "ckpts/ss_dec_conv3d_16l8_fp16.json",
    "ckpts/ss_dec_conv3d_16l8_fp16.safetensors",
]
DINO_PATTERNS = ["config.json", "model.safetensors", "preprocessor_config.json"]


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _snapshot(repo_id: str, local_dir: Path, allow_patterns: list[str]) -> None:
    from huggingface_hub import snapshot_download

    local_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        allow_patterns=allow_patterns,
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,
        max_workers=4,
    )


def ensure_models(models_dir: Path) -> Path:
    """Download the no-access FP8 TRELLIS.2 stack needed for image->textured GLB."""
    trellis_root = models_dir / "visualbruno" / "TRELLIS.2-4B-FP8"
    sparse_decoder_root = models_dir / "microsoft" / "TRELLIS-image-large"
    dino_root = models_dir / "facebook" / "dinov3-vitl16-pretrain-lvd1689m"

    if not (trellis_root / "pipeline_fp8.json").exists():
        print(f"downloading {FP8_REPO} FP8 model files", flush=True)
    _snapshot(FP8_REPO, trellis_root, FP8_PATTERNS)

    if not (sparse_decoder_root / "ckpts" / "ss_dec_conv3d_16l8_fp16.safetensors").exists():
        print(f"downloading {SPARSE_DECODER_REPO} sparse decoder", flush=True)
    _snapshot(SPARSE_DECODER_REPO, sparse_decoder_root, SPARSE_DECODER_PATTERNS)

    if not (dino_root / "model.safetensors").exists():
        print(f"downloading public DINOv3 ViT-L conditioning model from {DINO_REPO}", flush=True)
    _snapshot(DINO_REPO, dino_root, DINO_PATTERNS)

    return trellis_root


def configure_runtime(models_dir: Path, trellis_src: Path) -> None:
    """Set runtime knobs before importing TRELLIS.2."""
    os.environ["TRELLIS2_MODELS_DIR"] = str(models_dir)
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    os.environ.setdefault("ATTN_BACKEND", "sdpa")
    os.environ.setdefault("SPARSE_ATTN_BACKEND", "flash_attn")
    os.environ.setdefault("SPARSE_CONV_BACKEND", "flex_gemm")

    shim_dir = Path(__file__).resolve().parent / "trellis2_shims"
    for p in (str(shim_dir), str(trellis_src)):
        if p not in sys.path:
            sys.path.insert(0, p)

    import folder_paths  # type: ignore

    folder_paths.models_dir = str(models_dir)


def configure_torch() -> str:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("TRELLIS.2 FP8 needs CUDA; torch.cuda.is_available() is false")

    try:
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True
        torch.set_float32_matmul_precision("high")
    except Exception:
        pass

    props = torch.cuda.get_device_properties(0)
    cc = torch.cuda.get_device_capability(0)
    print(f"cuda {props.name} cc={cc[0]}.{cc[1]} vram={props.total_memory / 1e9:.1f}GB", flush=True)
    return f"cuda:{props.name}"


def preprocess_image(path: Path, remove_background: bool):
    import numpy as np
    from PIL import Image, ImageOps

    with Image.open(path) as src:
        img = ImageOps.exif_transpose(src).convert("RGBA")

    if max(img.size) > 1536:
        img.thumbnail((1536, 1536), Image.Resampling.LANCZOS)

    has_alpha = np.asarray(img.getchannel("A")).min() < 250
    if remove_background and not has_alpha:
        try:
            from rembg import remove

            print("removing background", flush=True)
            img = remove(img.convert("RGB")).convert("RGBA")
            has_alpha = True
        except Exception as e:  # noqa: BLE001
            print(f"background removal skipped: {e}", flush=True)

    if has_alpha:
        arr = np.asarray(img)
        alpha = arr[:, :, 3]
        ys, xs = np.where(alpha > 16)
        if len(xs) and len(ys):
            x0, x1 = xs.min(), xs.max()
            y0, y1 = ys.min(), ys.max()
            pad = int(max(x1 - x0 + 1, y1 - y0 + 1) * 0.08)
            x0 = max(0, x0 - pad)
            y0 = max(0, y0 - pad)
            x1 = min(img.width - 1, x1 + pad)
            y1 = min(img.height - 1, y1 + pad)
            img = img.crop((x0, y0, x1 + 1, y1 + 1))
        arr = np.asarray(img).astype("float32") / 255.0
        rgb = arr[:, :, :3] * arr[:, :, 3:4]
        img = Image.fromarray((rgb * 255).clip(0, 255).astype("uint8"), mode="RGB")
    else:
        img = img.convert("RGB")

    return img


def _export_vertex_color_glb(mesh, out_path: Path, model_name: str, seconds: float) -> str:
    import numpy as np
    import trimesh

    vertex_attrs = mesh.query_vertex_attrs()
    layout = getattr(mesh, "layout", {}) or {}
    rgb_slice = layout.get("base_color", slice(0, 3))
    alpha_slice = layout.get("alpha")

    rgb = vertex_attrs[..., rgb_slice].detach().float().cpu().numpy()
    rgb = np.squeeze(rgb)
    if rgb.ndim == 1:
        rgb = rgb[None, :]
    rgb = np.clip(rgb * 255, 0, 255).astype(np.uint8)

    if alpha_slice is not None:
        alpha = vertex_attrs[..., alpha_slice].detach().float().cpu().numpy()
        alpha = np.squeeze(alpha)
        if alpha.ndim == 1:
            alpha = alpha[:, None]
        alpha = np.clip(alpha * 255, 0, 255).astype(np.uint8)
    else:
        alpha = np.full((rgb.shape[0], 1), 255, dtype=np.uint8)
    rgba = np.concatenate([rgb, alpha], axis=-1)

    vertices = mesh.vertices.detach().float().cpu().numpy()
    faces = mesh.faces.detach().cpu().numpy()
    vertices[:, 1], vertices[:, 2] = vertices[:, 2].copy(), -vertices[:, 1].copy()

    out_mesh = trimesh.Trimesh(
        vertices=vertices,
        faces=faces,
        vertex_colors=rgba,
        process=False,
    )
    out_mesh.metadata["extras"] = {
        "model": model_name,
        "texture": "trellis2-pbr-vertex-bake",
        "seconds": seconds,
    }
    out_mesh.export(str(out_path))
    return "vertex-color"


def export_textured_glb(pipe, mesh, out_path: Path, *, resolution: int, texture_size: int, mode: str, seconds: float) -> str:
    import torch
    import trimesh
    from trellis2.modules.sparse import SparseTensor

    if getattr(mesh, "attrs", None) is None or getattr(mesh, "coords", None) is None:
        return _export_vertex_color_glb(mesh, out_path, FP8_REPO, seconds)

    if mode == "vertex":
        return _export_vertex_color_glb(mesh, out_path, FP8_REPO, seconds)

    coords = mesh.coords
    if coords.shape[-1] == 3:
        coords = torch.cat([torch.zeros_like(coords[:, :1]), coords], dim=-1)
    pbr_voxel = SparseTensor(mesh.attrs, coords)

    base_mesh = trimesh.Trimesh(
        vertices=mesh.vertices.detach().float().cpu().numpy(),
        faces=mesh.faces.detach().cpu().numpy(),
        process=False,
    )

    try:
        textured_mesh, _base_color, _metallic_roughness = pipe.postprocess_mesh(
            base_mesh,
            pbr_voxel,
            resolution=int(resolution),
            texture_size=int(texture_size),
            texture_alpha_mode="OPAQUE",
            double_side_material=True,
            bake_on_vertices=False,
            use_custom_normals=False,
            mesh_cluster_threshold_cone_half_angle_rad=60.0,
            inpainting="telea",
        )
        textured_mesh.metadata["extras"] = {
            "model": FP8_REPO,
            "texture": "trellis2-pbr-texture-map",
            "texture_size": texture_size,
            "seconds": seconds,
        }
        textured_mesh.export(str(out_path))
        return "pbr-texture"
    except Exception as e:  # noqa: BLE001
        print(f"PBR texture map bake failed, using vertex-color texture bake: {e}", flush=True)
        return _export_vertex_color_glb(mesh, out_path, FP8_REPO, seconds)


def run(args: argparse.Namespace) -> dict[str, Any]:
    t0 = time.time()
    models_dir = Path(args.models_dir).resolve()
    trellis_src = Path(args.trellis_src).resolve()

    configure_runtime(models_dir, trellis_src)
    device_label = configure_torch()

    model_root = ensure_models(models_dir)
    if args.download_only:
        return {"ok": True, "kind": KIND, "download_only": True, "model_root": str(model_root)}

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    from comfy.utils import ProgressBar  # type: ignore
    from PIL import Image
    from trellis2.pipelines.trellis2_image_to_3d import Trellis2ImageTo3DPipeline

    image = preprocess_image(Path(args.input), args.remove_background)
    if not isinstance(image, Image.Image):
        raise RuntimeError("image preprocessing returned an invalid image")

    print(f"loading {FP8_REPO}", flush=True)
    pipe = Trellis2ImageTo3DPipeline.from_pretrained(
        str(model_root),
        keep_models_loaded=False,
        use_fp8=True,
    )
    pipe.low_vram = True
    pipe.cuda()

    print(
        "generating textured mesh "
        f"pipeline={args.pipeline} sparse={args.sparse_steps} shape={args.shape_steps} "
        f"texture={args.texture_steps} tokens={args.max_tokens}",
        flush=True,
    )
    pbar = ProgressBar(5)
    result = pipe.run(
        image=image,
        num_samples=1,
        seed=int(args.seed),
        sparse_structure_sampler_params={"steps": int(args.sparse_steps)},
        shape_slat_sampler_params={"steps": int(args.shape_steps)},
        tex_slat_sampler_params={"steps": int(args.texture_steps)},
        preprocess_image=False,
        return_latent=True,
        pipeline_type=args.pipeline,
        max_num_tokens=int(args.max_tokens),
        sparse_structure_resolution=int(args.sparse_resolution),
        max_views=1,
        generate_texture_slat=True,
        use_tiled=True,
        pbar=pbar,
        sampler=args.sampler,
        verbose=False,
        fill_holes=True,
        hole_iterations=1,
        hole_fill_algorithm="remove_small_holes",
        keep_only_shell=True,
    )

    meshes, (_shape_slat, _tex_slat, resolution) = result
    if not meshes:
        raise RuntimeError("TRELLIS.2 returned no mesh")

    seconds = time.time() - t0
    texture_mode = export_textured_glb(
        pipe,
        meshes[0],
        out_path,
        resolution=int(resolution),
        texture_size=int(args.texture_size),
        mode=args.export_mode,
        seconds=seconds,
    )

    try:
        import torch

        torch.cuda.synchronize()
        torch.cuda.empty_cache()
    except Exception:
        pass

    size = out_path.stat().st_size if out_path.exists() else 0
    if size <= 0:
        raise RuntimeError(f"TRELLIS.2 export produced an empty file: {out_path}")

    return {
        "ok": True,
        "kind": KIND,
        "output": str(out_path),
        "bytes": size,
        "seconds": round(time.time() - t0, 2),
        "device": device_label,
        "pipeline": args.pipeline,
        "texture": texture_mode,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Jarvis TRELLIS.2 FP8 image-to-3D worker")
    p.add_argument("--input", required=False, help="Input image path")
    p.add_argument("--output", required=False, help="Output GLB path")
    p.add_argument("--models-dir", required=True, help="TRELLIS.2 models root")
    p.add_argument("--trellis-src", required=True, help="ComfyUI-Trellis2 source directory")
    p.add_argument("--seed", type=int, default=3407)
    p.add_argument("--pipeline", default="512", choices=["512", "1024", "1024_cascade"])
    p.add_argument("--sampler", default="euler", choices=["euler", "heun", "rk4", "rk5"])
    p.add_argument("--sparse-steps", type=int, default=8)
    p.add_argument("--shape-steps", type=int, default=8)
    p.add_argument("--texture-steps", type=int, default=8)
    p.add_argument("--max-tokens", type=int, default=49152)
    p.add_argument("--sparse-resolution", type=int, default=32)
    p.add_argument("--texture-size", type=int, default=1024)
    p.add_argument("--export-mode", default="texture", choices=["texture", "vertex"])
    p.add_argument("--remove-background", action="store_true")
    p.add_argument("--download-only", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = run(args)
        _print_json(payload)
        return 0
    except Exception as e:  # noqa: BLE001
        _print_json({"ok": False, "kind": KIND, "error": f"{type(e).__name__}: {e}"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
