# JARVIS Research Notes

This project is aiming for a lawful, local, cinematic JARVIS-style assistant,
not a distribution of Marvel-owned dialogue, movie audio, or a clone of a
living actor's voice.

## Source Signals

- Character identity: J.A.R.V.I.S. is associated with Tony Stark's AI assistant
  in the MCU and is voiced by Paul Bettany.
  Source: https://en.wikipedia.org/wiki/J.A.R.V.I.S.
- MCU behavior pattern: formal assistant, systems control, diagnostics,
  mission support, armor/lab integration, dry composure.
  Source: https://marvelcinematicuniverse.fandom.com/wiki/J.A.R.V.I.S.
- Voice direction: closest legal local/browser match is a British male TTS
  voice. The implementation prioritizes Microsoft Ryan/George, Google UK
  English Male, Daniel, Oliver, Arthur, and related en-GB voices.
  Sources:
  - https://support.microsoft.com/en-us/accessibility/windows/narrator/appendix-a-supported-languages-and-voices
  - https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support
- Local model stability: Ollama thinking models may expose hidden reasoning
  separately from visible content, so the config disables reasoning effort for
  direct chat replies.
  Source: https://docs.ollama.com/capabilities/thinking
- External agent backend: Claude Code supports print mode and `--max-turns`
  through the official CLI, so JARVIS can delegate to an installed `claude`
  executable without copying or depending on leaked source.
  Source: https://code.claude.com/docs/en/cli-usage
- Open-source coding backend options:
  - OpenCode exposes a non-interactive `opencode -p "prompt"` mode.
    Source: https://github.com/opencode-ai/opencode
  - Codex exposes non-interactive `codex exec "prompt"` mode.
    Source: https://www.mintlify.com/openai/codex/advanced/exec-mode
- NVIDIA Jarvis/Riva voice path: the NGC `speechsynthesis_waveglow` asset is a
  WaveGlow vocoder component used inside a Tacotron2/WaveGlow TTS pipeline. It
  is not a complete MCU JARVIS voice file. Use it through a deployed Riva TTS
  server with proper NVIDIA licensing and credentials.
  Sources:
  - https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tlt-jarvis/models/speechsynthesis_waveglow?version=deployable_v1.0
  - https://docs.nvidia.com/deeplearning/riva/user-guide/docs/tutorials/tts-deploy.html
  - https://docs.nvidia.com/deeplearning/riva/archives/121-b/user-guide/docs/user_guide_tts.html

## Implementation Mapping

- Persona: concise British butler-AI, status/diagnosis/action structure,
  protective but not reckless.
- Reply guard: empty, echo, and malformed local-model replies trigger a repair
  pass before anything reaches the UI.
- Voice: browser TTS ranks legitimate British male voices first and exposes the
  selected voice tier in the HUD.
- HUD: boot telemetry, protocol panel, model/tool/voice status, and diagnostic
  language are tuned for a mission-control feel.
- Agent backend: `agent_backend_status` detects Claude Code, Codex, and
  OpenCode. `agent_backend_run` launches the chosen CLI in non-interactive mode
  after JARVIS permission handling.
- NVIDIA voice: `/api/tts/status` exposes both the current Ryan fallback and
  the optional Riva/Jarvis path. `/api/tts` tries Riva only when configured,
  then falls back to Ryan so the interface does not go silent.

## Legal Boundary

Do not add copyrighted movie clips, ripped audio, exact long script dialogue, or
any tool that imitates Paul Bettany's voice without explicit rights and consent.
Keep the assistant as a high-fidelity inspired local system.

Do not import leaked or DMCA-sensitive Claude Code source into this repository.
Use official installed CLIs or genuinely open-source agent projects instead.
