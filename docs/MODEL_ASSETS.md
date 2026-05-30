# Model Assets

This repository intentionally does not include large model binaries, generated
media, local memories, logs, virtual environments, or dependency installs.
Those files are local runtime state and can exceed GitHub's upload limits.

## FLUX image generation

The image generation plugin uses FLUX.2-klein-4B through a GGUF transformer
file.

- Hugging Face repository: https://huggingface.co/unsloth/FLUX.2-klein-4B-GGUF
- File to download: `flux-2-klein-4b-BF16.gguf`
- Place it at: `data/models/flux-2-klein-4b-BF16.gguf`
- Base pipeline components: https://huggingface.co/black-forest-labs/FLUX.2-klein-4B

If the file is missing, `jarvis/plugins/media_generation.py` attempts to
download it automatically with `huggingface_hub` on first use.

The required Python packages are listed in `requirements.txt`; the FLUX path
expects `torch`, `diffusers>=0.38.0`, `transformers`, `accelerate`,
`sentencepiece`, `safetensors`, `huggingface-hub`, and `gguf`.

Generated images are written under `data/generated/images/`, which is ignored
by Git.

## Piper JARVIS-style voice

The optional Piper path uses a community voice model.

- Hugging Face repository: https://huggingface.co/jgkawell/jarvis
- Model file: `en_GB-jarvis-medium.onnx`
- Metadata file: matching `.onnx.json`
- Place them at:
  - `data/voices/jarvis.onnx`
  - `data/voices/jarvis.onnx.json`

Install Piper with:

```bat
pip install piper-tts
```

Then keep `voice.piper_enabled: true` in `config.yaml`.

## Default behavior without downloads

JARVIS still runs without these local assets. Image generation downloads the
FLUX asset lazily when needed, and voice output falls back to Microsoft Edge TTS
when Piper is unavailable.
