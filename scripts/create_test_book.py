from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "mvp-test-book.epub"
OUT.parent.mkdir(parents=True, exist_ok=True)

chapters = [
    ("01.xhtml", "Chapitre 1 - Introduction", "Ce livre de test contient des phrases courtes. Il contient aussi des accents français : é, è, ê, ç et œ."),
    ("02.xhtml", "Chapitre 2 - Ponctuation", "Une question ? Une exclamation ! Une citation : « ceci est un test ». Les pauses et la ponctuation doivent rester naturelles."),
    ("03.xhtml", "Chapitre 3 - Dialogue", "Paul dit : Bonjour, comment vas-tu ? Marie répond : Très bien, merci. Ils poursuivent leur discussion calmement."),
    ("04.xhtml", "Chapitre 4 - Long paragraphe", "Ce paragraphe est volontairement plus long afin de tester le découpage en segments audio, la reprise après interruption et la régénération ciblée d’un segment. La lecture doit rester compréhensible, régulière et agréable, sans répétition ni mot manquant."),
]

container = """<?xml version='1.0' encoding='UTF-8'?><container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'><rootfiles><rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/></rootfiles></container>"""
manifest = "\n".join(f"<item id='c{i}' href='{href}' media-type='application/xhtml+xml'/>" for i, (href, _, _) in enumerate(chapters, 1))
spine = "".join(f"<itemref idref='c{i}'/>" for i in range(1, len(chapters) + 1))
opf = f"""<?xml version='1.0' encoding='UTF-8'?><package xmlns='http://www.idpf.org/2007/opf' version='3.0'><metadata xmlns:dc='http://purl.org/dc/elements/1.1/'><dc:title>Test Audiobook MVP</dc:title><dc:creator>TTSDocReader</dc:creator></metadata><manifest>{manifest}</manifest><spine>{spine}</spine></package>"""

with ZipFile(OUT, "w", ZIP_DEFLATED) as archive:
    archive.writestr("mimetype", "application/epub+zip", compress_type=0)
    archive.writestr("META-INF/container.xml", container)
    archive.writestr("OEBPS/content.opf", opf)
    for href, title, body in chapters:
        archive.writestr(f"OEBPS/{href}", f"<html><body><h1>{title}</h1><p>{body}</p></body></html>")
print(OUT)
