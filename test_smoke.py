from app.text_extract import extract_text
from app.chunking import iter_chunks
from pathlib import Path
p = Path("sample.txt")
text = extract_text(p)
chunks = list(iter_chunks(text, max_chars=80))
print("EXTRACT_LEN=", len(text))
print("CHUNKS=", len(chunks))
for i, c in enumerate(chunks[:5], 1):
    print(f"[{i}]", c)
