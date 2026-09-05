from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import wave
from unittest.mock import patch

from app.config import settings
from app.pipeline import synthesize_document
from app.tts import OrpheusEngine


class PipelineTests(unittest.TestCase):
    def test_mock_backend_synthesizes_text_file(self):
        source = Path(__file__).with_name("sample.txt")
        with TemporaryDirectory() as tmp:
            OrpheusEngine._instance = None
            with patch.object(settings, "output_dir", tmp):
                output = synthesize_document(source, backend="mock", audio_format="wav")
            self.assertTrue(output.exists())
            with wave.open(output.as_posix(), "rb") as audio:
                self.assertEqual(audio.getnchannels(), 1)
                self.assertGreater(audio.getnframes(), 0)


if __name__ == "__main__":
    unittest.main()
