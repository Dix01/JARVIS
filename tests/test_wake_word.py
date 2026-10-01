"""Config-to-HTTP contract for the browser's wake phrase (no audio/models)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jarvis.config import Config, VoiceConfig, load_config
from jarvis.server.routes import router


class WakeWordTests(unittest.TestCase):
    def health_from_yaml(self, yaml_text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(yaml_text, encoding="utf-8")
            # Tests must not load the developer's API keys from .env.
            with patch("jarvis.config.load_dotenv"):
                cfg = load_config(path)
        app = FastAPI()
        app.state.cfg = cfg
        app.state.orchestrator = None
        app.state.memory = None
        app.state.registry = SimpleNamespace(plugins=lambda: [], all_tools=lambda: [])
        app.state.agents = SimpleNamespace(names=lambda: [])
        app.include_router(router, prefix="/api")
        with TestClient(app) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_old_configs_keep_default_phrase(self):
        for yaml_text in ["", "voice: {}", "voice:\n  provider: auto\n"]:
            with self.subTest(yaml=yaml_text):
                self.assertEqual(self.health_from_yaml(yaml_text)["voice"]["wake_word"], "Hey JARVIS")
        self.assertEqual(Config().voice.wake_word, "Hey JARVIS")

    def test_custom_phrases_reach_browser_health_payload(self):
        for phrase, expected in [(" Hey   Friday ", "Hey Friday"), ("贾维斯", "贾维斯"), ("Assistant+", "Assistant+")]:
            with self.subTest(phrase=phrase):
                result = self.health_from_yaml(f'voice:\n  wake_word: "{phrase}"\n')
                self.assertEqual(result["voice"], {"wake_word": expected})

    def test_blank_and_non_string_phrases_are_rejected(self):
        for phrase in ["", " \t\n ", None, 42]:
            with self.subTest(phrase=phrase), self.assertRaises(ValidationError):
                VoiceConfig(wake_word=phrase)


if __name__ == "__main__":
    unittest.main()
