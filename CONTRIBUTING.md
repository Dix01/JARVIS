# Contributing to J.A.R.V.I.S.

First off — thanks for being here. JARVIS is a local-first AI mission control, and
it gets better every time someone adds a tool, a HUD panel, a voice, or a model
backend. This guide gets you from clone to merged PR.

New here? The fastest, most satisfying first contribution is **adding a tool** —
see [Add a tool in one file](#add-a-tool-in-one-file). It's genuinely ~30 lines.

---

## Ways to contribute

- 🛠️ **New tools / plugins** — give JARVIS a new capability (a file in `jarvis/plugins/`).
- 🪟 **HUD panels & polish** — new visualizations, animations, or panels in `web/`.
- 🧩 **Model providers** — wire up another OpenAI-compatible endpoint or voice engine.
- 🐛 **Bug fixes** — grab anything in [Issues](https://github.com/Dix01/JARVIS/issues).
- 📖 **Docs** — clearer setup, troubleshooting, examples. Always welcome.
- 💡 **Ideas** — open a [feature request](https://github.com/Dix01/JARVIS/issues/new/choose).

No contribution is too small. Typo fixes count.

---

## Project layout

```
jarvis/        Python backend — server routes, orchestrator, agents, tool plugins
  plugins/     Each *.py here is a tool group, auto-discovered at startup
  agents/      The 9-role agent matrix
  core/        Orchestrator, memory, permissions, VRAM manager, events
  workers/     Isolated subprocess workers (e.g. TRELLIS 3D)
web/           React + Three.js HUD frontend
electron/      Desktop shell
docs/          Model download guide, screenshots
config.yaml    All configuration (persona, model, voice, permissions, plugins)
```

---

## Dev setup

**Requirements:** Windows 10/11 · Python 3.10+ · Node 18+ · (NVIDIA GPU optional, for
image/3D/Whisper).

```bat
:: 1. Fork + clone your fork
git clone https://github.com/<you>/JARVIS.git
cd JARVIS

:: 2. Backend venv + frontend deps + Electron
setup.bat

:: 3. Configure (point model.endpoint at your LLM)
copy .env.example .env
notepad config.yaml

:: 4. Run with frontend hot-reload
run-dev.bat
```

Backend serves on `http://127.0.0.1:7341`. `run-dev.bat` gives you Vite hot-reload on
the HUD; backend changes need a restart.

---

## Add a tool in one file

A plugin is any module in `jarvis/plugins/` that exposes a `register(registry)`
function. Define handlers with the `@tool(...)` decorator, then claim them in
`register()`. That's the whole contract — the registry auto-discovers your file at
startup.

Create `jarvis/plugins/hello_tools.py`:

```python
from ..core.permissions import Permission
from .base import PluginInfo, tool


@tool(
    name="say_hello",
    description="Greet someone by name.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Who to greet"}},
        "required": ["name"],
    },
    permission=Permission.SAFE,   # SAFE | CAUTION | DANGEROUS
)
def say_hello(name: str) -> str:
    return f"Hello, {name}."


def register(registry):
    registry.add_pending("hello_tools")           # claim every @tool defined above
    registry.register_plugin(
        PluginInfo(name="hello_tools", description="Demo greeting tool.")
    )
```

Restart the backend and ask JARVIS to greet someone — it picks the tool by itself.
Handlers may be sync **or** `async`; both work. To ship a tool **disabled by
default**, add it under `plugins:` in `config.yaml`.

### Picking a permission tier

| Tier | Use for |
|---|---|
| `Permission.SAFE` | Read-only / low-risk. Runs automatically. |
| `Permission.CAUTION` | Writes, network calls, anything reversible-but-real. Prompts for confirmation. |
| `Permission.DANGEROUS` | Deletes, system mutation, money/email. Explicit approval. |

When in doubt, tier **up**. The denylist (`rm -rf /`, `format c:`, fork bombs, …) is
enforced regardless of tier — don't try to route around it.

---

## Frontend notes

- Stack: **React 18 · TypeScript · Three.js** (`@react-three/fiber` + `drei`) ·
  **Framer Motion · Zustand · Tailwind · Vite · Electron**.
- State lives in `web/src/lib/store.ts` (Zustand, persisted to localStorage).
- WebSocket/event wiring is in `web/src/lib/ws.ts` — it only **adds** to chat/media,
  never wipes. Keep that invariant.
- Keep TypeScript strict-clean: `cd web && npm run build` should pass.

---

## Style

- **Python** — type hints, `from __future__ import annotations`, prefer small pure
  functions. Match the surrounding file.
- **TypeScript** — strict, no `any` unless truly unavoidable.
- Keep it terse. No dead code, no commented-out blocks.

---

## Safety & privacy rules

These are hard rules — PRs that break them won't merge:

- ❌ **Never commit secrets.** `.env`, API keys, tokens. (It's git-ignored — keep it that way.)
- ❌ **Never commit model weights** or large binaries. They download lazily; see
  [docs/MODEL_ASSETS.md](docs/MODEL_ASSETS.md).
- ❌ **Never commit personal data** — real faces, generated media from `data/`, memory
  DBs, logs. All of `data/` is git-ignored; don't force it in.
- ✅ **Respect the permission tiers** above for every new tool.

---

## PR checklist

Before opening a pull request:

- [ ] Branch off `main`, descriptive name (`feat/spotify-tool`, `fix/webcam-leak`).
- [ ] `cd web && npm run build` passes (if you touched the frontend).
- [ ] Backend starts clean (`run.bat`) with your change.
- [ ] New tools declare a sensible `Permission` tier.
- [ ] No secrets, weights, or `data/` artifacts in the diff.
- [ ] README/docs updated if behavior or setup changed.

Commit messages: short imperative subject (`Add Spotify control tool`), details in the
body. Squash noisy WIP commits before review if you can.

---

## Questions?

Open a [Discussion](https://github.com/Dix01/JARVIS/discussions) or a
[draft PR](https://github.com/Dix01/JARVIS/pulls) and ask. Happy building. 🚀
