# Local model cache

Large model binaries are not committed to this repository.

Expected optional FLUX image model:

- Repository: https://huggingface.co/unsloth/FLUX.2-klein-4B-GGUF
- File: `flux-2-klein-4b-BF16.gguf`
- Local path: `data/models/flux-2-klein-4b-BF16.gguf`

The media generation plugin can download this file automatically on first use
through `huggingface_hub`. Manual downloads should be placed at the path above.

Additional selectable Z-Image text encoder:

- Repository: https://huggingface.co/BennyDaBall/Qwen3-4b-Z-Image-Turbo-AbliteratedV1
- File: `Z-Image-AbliteratedV1.Q8_0.gguf`
- Local path: `data/models/Z-Image-AbliteratedV1.Q8_0.gguf`

JARVIS can select between available image backends from the command bar image
model menu or `/image-model <id>`.
