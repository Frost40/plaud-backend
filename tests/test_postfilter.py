import pytest
from app.pipeline_filters import clean

def test_blocklist_filter():
    blocklist = ["Thanks for watching", "Sottotitoli a cura di"]
    text = "Hello world.\nThanks for watching\nThis is a test."
    res = clean(text, blocklist)
    assert "Thanks for watching" not in res
    assert "Hello world." in res
    assert "This is a test." in res

def test_blocklist_normalization_filter():
    blocklist = ["Thank you for watching"]
    # Should match even with slightly different casing/punctuation
    text = "Hello world.\nThank you for watching!\nThis is a test."
    res = clean(text, blocklist)
    assert "Thank you for watching" not in res
    assert "Hello world." in res
    assert "This is a test." in res

def test_repetition_filter():
    text = "This is a sentence. It represents a block of text.\n\nThis is a sentence. It represents a block of text.\n\nDifferent text here."
    res = clean(text, [])
    # Second paragraph should be filtered out due to similarity > 0.85
    assert "Different text here." in res
    assert res.count("This is a sentence.") == 1

def test_whitespace_cleanup():
    text = "Hello.\n\n\n\n\nWorld.\n   "
    res = clean(text, [])
    assert res == "Hello.\n\nWorld."
