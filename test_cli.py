from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from audiobook_cli import load_chapter_titles


class CliTests(unittest.TestCase):
    def test_loads_powershell_utf8_bom_json(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "titles.json"
            path.write_text('["Titre corrigé"]', encoding="utf-8-sig")
            self.assertEqual(load_chapter_titles(path), ["Titre corrigé"])


if __name__ == "__main__":
    unittest.main()
