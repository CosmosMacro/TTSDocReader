from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.books import Book, Chapter, apply_chapter_titles, load_book


class BookImportTests(unittest.TestCase):
    def test_epub_import_preserves_spine_chapters_and_metadata(self):
        with TemporaryDirectory() as tmp:
            epub = Path(tmp) / "sample.epub"
            from zipfile import ZipFile
            with ZipFile(epub, "w") as z:
                z.writestr("META-INF/container.xml", """<?xml version='1.0'?>
                    <container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>
                      <rootfiles><rootfile full-path='OPS/content.opf' media-type='application/oebps-package+xml'/></rootfiles>
                    </container>""")
                z.writestr("OPS/content.opf", """<?xml version='1.0'?>
                    <package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
                      <metadata xmlns:dc='http://purl.org/dc/elements/1.1/'><dc:title>Psychiatrie en pratique</dc:title><dc:creator>Dr Test</dc:creator></metadata>
                      <manifest><item id='nav' href='nav.xhtml' media-type='application/xhtml+xml' properties='nav'/><item id='c1' href='chapter1.xhtml' media-type='application/xhtml+xml'/><item id='c2' href='chapter2.xhtml' media-type='application/xhtml+xml'/></manifest>
                      <spine><itemref idref='c1'/><itemref idref='c2'/></spine>
                    </package>""")
                z.writestr("OPS/chapter1.xhtml", "<html><body><h1>Titre interne erroné</h1><p>Premier chapitre.</p></body></html>")
                z.writestr("OPS/chapter2.xhtml", "<html><body><h1>Conclusion interne</h1><p>Dernier chapitre.</p></body></html>")
                z.writestr("OPS/nav.xhtml", "<html><body><nav epub:type='toc'><ol><li><a href='chapter1.xhtml'>Introduction clinique</a></li><li><a href='chapter2.xhtml'>Conclusion clinique</a></li></ol></nav></body></html>")
            book = load_book(epub)
            self.assertEqual(book.title, "Psychiatrie en pratique")
            self.assertEqual(book.author, "Dr Test")
            self.assertEqual([c.title for c in book.chapters], ["Introduction clinique", "Conclusion clinique"])
            self.assertEqual(book.chapters[0].text, "Premier chapitre.")

    def test_heading_detection_can_split_plain_text(self):
        text = "Avant-propos\n\nChapitre 1 - Bases\n\nLes bases.\n\nChapitre 2 - Suite\n\nLa suite."
        from app.books import split_text_into_chapters
        chapters = split_text_into_chapters(text)
        self.assertEqual([c.title for c in chapters], ["Avant-propos", "Chapitre 1 - Bases", "Chapitre 2 - Suite"])
        self.assertEqual(chapters[1].text, "Les bases.")

    def test_chapter_titles_can_be_corrected_without_changing_text(self):
        book = Book("Book", None, Path("book.epub"), [Chapter("Detected", "Body", 1)])
        corrected = apply_chapter_titles(book, ["Corrected title"])
        self.assertEqual(corrected.chapters[0].title, "Corrected title")
        self.assertEqual(corrected.chapters[0].text, "Body")


if __name__ == "__main__":
    unittest.main()
