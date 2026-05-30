# J.A.R.V.I.S.

Local-first AI command center for Windows.

J.A.R.V.I.S. pairs a React/Three.js HUD with a FastAPI backend, local memory,
tool plugins, browser control, voice, vision, media generation, and agent CLI
delegation.

![J.A.R.V.I.S. HUD](docs/images/dashboard.png)

## What It Can Do

- Chat through an OpenAI-compatible model endpoint, or through Anthropic's
  Messages API when `provider: anthropic` is configured.
- Search the web, news, images, and videos; fetch readable page text; show
  results as cards inside the Media Bay.
- Control a visible Chromium browser through Playwright: open pages, read text,
  click, type, press keys, and take screenshots.
- Work on the local machine: files, folders, shell commands, Python snippets,
  Node snippets, package installs, project scans, and debug loops.
- Monitor the PC: CPU, RAM, GPU, disk, network, battery, and process details.
- Use voice: browser microphone input and speech output, server-side
  faster-whisper STT, Piper local TTS, NVIDIA Riva TTS, and Edge TTS fallback.
- Use vision: screenshots, webcam snapshots, live webcam preview, OCR, and
  image analysis through the configured multimodal model.
- Remember things locally: SQLite conversation memory, notes, preferences,
  paths, known fixes, tool history, command history, and a memory galaxy view.
- Generate media locally with FLUX.2-klein-4B GGUF; generated images stay in
  ignored local runtime folders.
- Build 3D assets when optional 3D dependencies are installed: text-to-3D goes
  through FLUX image generation, then image-to-3D via Stable Fast 3D or TripoSR.
- Delegate long-running goals to installed Claude Code, Codex, or OpenCode CLI
  backends.
- Use optional plugins for a local JSON calendar, SMTP email, and Home
  Assistant smart-home control.
- Enforce tool permissions with SAFE, CAUTION, and DANGEROUS tiers, plus local
  action logs and edit backups.

## Quick Start

Clone with submodules:

```bat
git clone --recurse-submodules https://github.com/Dix01/J.A.R.V.I.S.git
cd J.A.R.V.I.S
```

Install and run:

```bat
setup.bat
copy .env.example .env
notepad .env
notepad config.yaml
run.bat
```

Open:

```text
http://127.0.0.1:7341
```

For hot reload during development:

```bat
run-dev.bat
```

## Model Assets

Large model files are not committed to this repository.

Download instructions live here:

- [Model asset guide](docs/MODEL_ASSETS.md)
- FLUX GGUF cache: `data/models/`
- Piper voice cache: `data/voices/`

The app can run without those files. It falls back where possible and downloads
some optional assets lazily on first use.

## Configure The Model

Edit `config.yaml`, then set the matching key in `.env`.

Example local setup:

```yaml
model:
  provider: openai_compatible
  endpoint: http://localhost:11434/v1
  model: your-model-name
  api_key_env: OLLAMA_API_KEY
```

For local OpenAI-compatible servers, point `endpoint` at LM Studio, Ollama,
vLLM, OpenAI, OpenRouter, or another compatible `/v1` backend. The `api_key_env`
value is the environment variable J.A.R.V.I.S. reads from `.env`.

## Main Folders

```text
jarvis/        Python backend, tools, agents, server routes
web/           React HUD frontend
docs/          Notes, research, model download instructions, screenshots
data/          Local runtime state, ignored caches, generated media
TripoSR/       Optional 3D generation submodule
stable-fast-3d Optional 3D generation submodule
```

If submodules are missing after cloning:

```bat
git submodule update --init --recursive
```

## Safety Model

J.A.R.V.I.S. separates tool calls into:

- `SAFE`: read-only or low-risk actions.
- `CAUTION`: actions that need confirmation.
- `DANGEROUS`: actions that require explicit approval or are refused.

Actions are logged locally under `data/logs/`, and file edits are backed up
under `data/backups/`.

## Useful Commands

```text
/help        Show commands
/tools       List tools
/agents      List agent personas
/memory ...  Search local memory
/mission ... Pin a project as the current focus
/reset       Clear the in-memory chat
```

## Notes

- Python virtual environments, `node_modules`, `.env`, logs, local memory,
  screenshots, generated output, reference/runtime images, and large model
  binaries are ignored by Git.
- This is a local desktop assistant project. Review tools and permissions
  before using it on sensitive files or systems.
