"""Configuration loader.

Reads `config.yaml` from the project root, merges in environment variables
from `.env`, validates with Pydantic, and exposes a typed `Config` object.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


class ModelConfig(BaseModel):
    provider: str = "openai_compatible"
    endpoint: str = "http://localhost:1234/v1"
    model: str = "local-model"
    api_key_env: str = "LLM_API_KEY"
    temperature: float = 0.3
    max_tokens: int = 4096
    request_timeout_seconds: int = 120
    native_tool_calls: bool = False
    reasoning_effort: str | None = None
    # Anti-repetition — light touch. Higher values degrade fluency and can
    # paradoxically push the model into longer loops. Ollama already
    # auto-translates `frequency_penalty` → repeat_penalty internally, so
    # we DO NOT also pass an `options.repeat_penalty` (double-penalty was
    # the cause of stream lag).
    frequency_penalty: float = 0.2
    presence_penalty: float = 0.0
    # Legacy Ollama-style repeat penalty. Kept for backward compat with any
    # cached bytecode that still references it; current brain.py does not
    # send it (frequency_penalty is auto-translated by Ollama server-side).
    repeat_penalty: float = 1.0

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")


class ImageModelConfig(BaseModel):
    selected: str = "flux2-klein"


class PermissionsConfig(BaseModel):
    mode: str = "confirm"
    denylist: list[str] = Field(default_factory=list)


class UIConfig(BaseModel):
    theme: str = "jarvis"
    emoji: bool = True
    show_status_bar: bool = True
    refresh_interval_ms: int = 1500


class MemoryConfig(BaseModel):
    db_path: str = "data/memory.db"
    auto_remember_user_preferences: bool = True


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "data/logs/jarvis.log"
    action_log: str = "data/logs/actions.jsonl"


class BackupConfig(BaseModel):
    enabled: bool = True
    dir: str = "data/backups"
    keep_last: int = 50


class CodeExecConfig(BaseModel):
    max_retries: int = 3
    timeout_seconds: int = 60
    workdir: str = "data/sandbox"
    allowed_runtimes: list[str] = Field(default_factory=lambda: ["python", "node"])


class ProjectConfig(BaseModel):
    watch_dirs: list[str] = Field(default_factory=list)
    ignore_patterns: list[str] = Field(default_factory=list)


class PluginToggle(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = False
    provider: str | None = None


class AssistantConfig(BaseModel):
    name: str = "JARVIS"
    persona: str = "You are JARVIS, a calm, precise, proactive local AI assistant."


class MissionConfig(BaseModel):
    enabled: bool = False
    project_path: str = ""


class UltimateConfig(BaseModel):
    """Master switch + per-feature toggles for the ULTIMATE upgrade.

    Every subsystem added by the upgrade checks its flag here, so the whole
    thing can be reversed at runtime by editing config.yaml — no git needed.
    Set `enabled: false` to fall back to baseline JARVIS behaviour entirely.
    """
    enabled: bool = True

    # — Intelligence —
    semantic_memory: bool = True
    embed_model: str = "text-embedding-3-small"
    # Blank → reuse the main model endpoint. Point elsewhere (e.g. a local
    # Ollama/LM-Studio embeddings server) to decouple embeddings from chat.
    embed_endpoint: str = ""
    recall_k: int = 5
    recall_min_score: float = 0.22
    auto_remember: bool = True
    context_compaction: bool = True
    compaction_trigger_messages: int = 28
    compaction_keep_recent: int = 12
    autonomous_planning: bool = True
    plan_min_chars: int = 60          # only plan for non-trivial requests

    # — Intuitive —
    proactive_suggestions: bool = True

    # — Gorgeous (frontend reads these via /health) —
    reactive_visuals: bool = True


class VoiceConfig(BaseModel):
    provider: str = "auto"  # auto | piper | edge_tts | nvidia_riva
    edge_voice: str = "en-GB-ThomasNeural"
    edge_rate: str = "-6%"
    edge_pitch: str = "+0Hz"
    # Piper (community JARVIS model, closest to Paul Bettany)
    piper_enabled: bool = False
    piper_model: str = "data/voices/jarvis.onnx"
    piper_speaker: int = 0
    piper_length_scale: float = 1.32
    piper_noise_scale: float = 0.55
    piper_noise_w_scale: float = 0.72
    piper_volume: float = 1.15
    riva_enabled: bool = False
    riva_server: str = "localhost:50051"
    riva_voice: str = "English-US.Female-1"
    riva_language_code: str = "en-US"
    riva_sample_rate_hz: int = 44100
    nvidia_waveglow_model_url: str = (
        "https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tlt-jarvis/"
        "models/speechsynthesis_waveglow?version=deployable_v1.0"
    )


class Config(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, protected_namespaces=())

    A: AssistantConfig = Field(default_factory=AssistantConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    image_model: ImageModelConfig = Field(default_factory=ImageModelConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    backups: BackupConfig = Field(default_factory=BackupConfig)
    code_execution: CodeExecConfig = Field(default_factory=CodeExecConfig)
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    plugins: dict[str, PluginToggle] = Field(default_factory=dict)
    agents: dict[str, PluginToggle] = Field(default_factory=dict)
    mission: MissionConfig = Field(default_factory=MissionConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    ultimate: UltimateConfig = Field(default_factory=UltimateConfig)

    project_root: Path = PROJECT_ROOT

    def abs_path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.project_root / p)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path | None = None) -> Config:
    if DEFAULT_ENV_PATH.exists():
        load_dotenv(DEFAULT_ENV_PATH)

    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        return Config()

    with cfg_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return Config(**raw)
