"""OPTIONAL: Voice input (STT) + output (TTS).

Disabled by default. Enable in config.yaml. Install optional deps first:
    pip install SpeechRecognition pyttsx3 sounddevice

If a microphone is not detected, STT degrades gracefully — JARVIS reports
'no microphone available' rather than crashing.
"""
from __future__ import annotations

import logging

from ..core.permissions import Permission
from .base import PluginInfo, tool

log = logging.getLogger("jarvis.plugins.voice")


def register(registry):
    # Try to detect hardware/deps. Tools still register; they report unavailability.
    try:
        import speech_recognition as sr  # noqa: F401
        _stt_ok = True
    except ImportError:
        _stt_ok = False

    try:
        import pyttsx3  # noqa: F401
        _tts_ok = True
    except ImportError:
        _tts_ok = False

    @tool(
        name="speak",
        description="Speak text aloud via the system's TTS engine (Windows SAPI by default).",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        preview=lambda a: f"TTS: {a.get('text','')[:60]}",
    )
    def speak(text: str) -> str:
        if not _tts_ok:
            return "pyttsx3 not installed (pip install pyttsx3)"
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        return f"spoke {len(text)} chars"

    @tool(
        name="listen",
        description="Capture a single utterance from the default microphone, return transcript. Requires a microphone.",
        permission=Permission.CAUTION,
        parameters={
            "type": "object",
            "properties": {"timeout": {"type": "integer", "default": 5}},
        },
        preview=lambda a: f"listen up to {a.get('timeout',5)}s",
    )
    def listen(timeout: int = 5) -> str:
        if not _stt_ok:
            return "SpeechRecognition not installed (pip install SpeechRecognition)"
        import speech_recognition as sr
        r = sr.Recognizer()
        try:
            with sr.Microphone() as src:
                audio = r.listen(src, timeout=timeout, phrase_time_limit=timeout)
        except OSError as e:
            return f"no microphone available: {e}"
        except AttributeError as e:
            return (
                "backend microphone unavailable (PyAudio not installed). "
                "JARVIS already uses the browser microphone via /api/stt. "
                f"Detail: {e}"
            )
        try:
            return r.recognize_google(audio)
        except sr.UnknownValueError:
            return "(could not understand audio)"
        except sr.RequestError as e:
            return f"STT request failed: {e}"

    @tool(
        name="microphone_status",
        description="Detect whether a microphone is currently available.",
        permission=Permission.SAFE,
        parameters={"type": "object", "properties": {}},
    )
    def microphone_status() -> str:
        if not _stt_ok:
            return "SpeechRecognition not installed"
        import speech_recognition as sr
        try:
            mics = sr.Microphone.list_microphone_names()
        except OSError as e:
            return f"audio backend error: {e}"
        except AttributeError as e:
            # PyAudio missing — backend-side mic enumeration unavailable.
            # JARVIS uses the BROWSER mic via MediaRecorder + /api/stt, so
            # this tool isn't required for voice input to work.
            return (
                "backend mic enumeration unavailable (PyAudio not installed). "
                "Browser mic via /api/stt is used instead and is independent of this. "
                "To enable backend mic listing: pip install pipwin && pipwin install pyaudio  "
                f"(detail: {e})"
            )
        if not mics:
            return "no microphones detected"
        return "microphones detected:\n" + "\n".join(f"- {m}" for m in mics)

    registry.add_pending("voice_tools_optional")
    registry.register_plugin(PluginInfo(
        name="voice_tools_optional",
        description="OPTIONAL voice: TTS, STT, mic detection.",
        permissions_needed=[Permission.CAUTION],
    ))
