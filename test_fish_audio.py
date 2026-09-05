import json
import unittest
from unittest.mock import patch

from app.fish_audio import FishAudioProvider, estimate_cost_usd


class FishAudioTests(unittest.TestCase):
    def test_estimate_uses_utf8_bytes_and_free_model(self):
        self.assertAlmostEqual(estimate_cost_usd("é" * 10, "s2.1-pro"), 0.0003)
        self.assertEqual(estimate_cost_usd("text", "s2.1-pro-free"), 0.0)

    def test_synthesize_posts_text_and_returns_audio(self):
        provider = FishAudioProvider("secret", model="s2.1-pro", reference_id="voice-1")

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b"fake-mp3"

        with patch("app.fish_audio.request.urlopen", return_value=Response()) as urlopen:
            result = provider.synthesize("Bonjour", voice=None)
        self.assertEqual(result, b"fake-mp3")
        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.fish.audio/v1/tts")
        self.assertEqual(json.loads(req.data), {"text": "Bonjour", "format": "mp3", "reference_id": "voice-1"})
        self.assertEqual(req.get_header("Authorization"), "Bearer secret")
        self.assertEqual(req.get_header("Model"), "s2.1-pro")


if __name__ == "__main__":
    unittest.main()
