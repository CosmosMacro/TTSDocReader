from app.chunking import chunk_text


def test_chunk_text_hard_wraps_a_single_overlong_sentence():
    source = "word " * 20
    chunks = chunk_text([source], max_chars=20)
    assert len(chunks) > 1
    assert all(len(chunk) <= 20 for chunk in chunks)
    assert " ".join(chunks).split() == source.split()
