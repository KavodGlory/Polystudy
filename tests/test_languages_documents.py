"""Tests for the language list and for reading, chunking and writing documents."""
import pytest

from tests.conftest import make_pdf
from translator import LANGUAGES, resolve_language, resolve_source
from translator.documents import (chunk_text, decode_text, extract_pdf_text, output_stem, reflow,
                                  write_html, write_txt)
from translator.errors import DocumentError


# ----------------------------------------------------------------- languages
def test_nine_languages():
    assert list(LANGUAGES) == ["en", "sw", "sheng", "ar", "fr", "ja", "es", "zh", "de"]


@pytest.mark.parametrize("arg, code", [
    ("fr", "fr"), ("French", "fr"), (" KISWAHILI ", "sw"), ("swahili", "sw"), ("Kenyan slang", "sheng"),
    ("sheng", "sheng"), ("chinese", "zh"), ("Chinese (Simplified)", "zh"), ("zh-CN", "zh"), ("english", "en"),
])
def test_resolve_language(arg, code):
    assert resolve_language(arg) == code


@pytest.mark.parametrize("arg", ["", None, "klingon", "auto"])
def test_resolve_language_rejects(arg):
    assert resolve_language(arg) is None          # "auto" is only valid as a source


@pytest.mark.parametrize("arg", [None, "", "auto", "Auto-detect"])
def test_resolve_source_auto(arg):
    assert resolve_source(arg) == "auto"


def test_resolve_source_language_and_unknown():
    assert resolve_source("German") == "de" and resolve_source("klingon") is None


def test_only_arabic_is_rtl():
    assert [c for c, l in LANGUAGES.items() if l.rtl] == ["ar"]


# ------------------------------------------------------------------ chunking
def _rebuild(chunks):
    return "".join(t + s for t, s in chunks).strip()


def test_short_text_is_one_chunk():
    assert chunk_text("Habari yako.", 3000) == [("Habari yako.", "")]


def test_chunks_respect_limit_and_keep_all_text_in_order():
    paragraphs = [f"Paragraph {i}. " + "word " * 120 for i in range(10)]
    text = "\n\n".join(p.strip() for p in paragraphs)
    chunks = chunk_text(text, 1000)
    assert len(chunks) > 1 and all(len(t) <= 1000 for t, _ in chunks)
    assert _rebuild(chunks) == text


def test_long_paragraph_is_split_at_sentence_ends():
    sentences = [f"This is sentence number {i}." for i in range(200)]
    chunks = chunk_text(" ".join(sentences), 500)
    assert all(len(t) <= 500 for t, _ in chunks)
    assert all(t.endswith(".") for t, _ in chunks)                 # never cut mid-sentence
    assert " ".join(t for t, _ in chunks) == " ".join(sentences)


def test_unbroken_text_is_hard_split_without_losing_characters():
    text = "x" * 2500
    chunks = chunk_text(text, 1000)
    assert all(len(t) <= 1000 for t, _ in chunks)
    assert "".join(t for t, _ in chunks) == text


def test_chunks_ending_a_paragraph_keep_blank_line_separator():
    chunks = chunk_text("a" * 600 + "\n\n" + "b" * 600, 700)
    assert chunks == [("a" * 600, "\n\n"), ("b" * 600, "")]


def test_chinese_text_without_spaces_is_chunked():
    text = "你好。" * 1000
    chunks = chunk_text(text, 500)
    assert all(len(t) <= 500 for t, _ in chunks) and "".join(t for t, _ in chunks) == text


# ------------------------------------------------------------------- reading
def test_decode_text_variants():
    assert decode_text("Habari\r\nyako".encode("utf-8")) == "Habari\nyako"
    assert decode_text("﻿شكراً".encode("utf-8")) == "شكراً"
    assert decode_text("こんにちは".encode("utf-16")) == "こんにちは"
    assert decode_text("café".encode("latin-1")) == "café"


def test_reflow_joins_wrapped_lines_but_keeps_headings():
    raw = ("Chapter One\n"
           "The quick brown fox jumps over the lazy dog and\n"
           "keeps running through the forest.\n\n"
           "Next paragraph.")
    out = reflow(raw)
    assert out.splitlines()[0] == "Chapter One"
    assert "lazy dog and keeps running through the forest." in out
    assert out.endswith("Next paragraph.")


def test_reflow_repairs_hyphenation_and_cjk():
    assert "information" in reflow("This sentence has a very long line that ends with infor-\nmation about it.")
    assert "你好世界" in reflow("这是一个很长的句子，一直延续到这一行的结尾而没有句号，你好\n世界，欢迎来到这里。")


def test_extract_pdf_text_and_reflow():
    pytest.importorskip("pypdf")
    pdf = make_pdf([["The quick brown fox jumps over the lazy dog and", "keeps running through the forest today."],
                    ["Second page text goes here, long enough to count as real text for the test."]])
    text, pages = extract_pdf_text(pdf)
    assert pages == 2
    assert "lazy dog and keeps running through the forest today." in text
    assert "Second page text" in text


def test_extract_pdf_text_rejects_garbage():
    with pytest.raises(DocumentError):
        extract_pdf_text(b"this is not a pdf")


# ------------------------------------------------------------------- writing
def test_write_txt_roundtrip():
    assert write_txt("شكراً\n日本語").decode("utf-8") == "شكراً\n日本語"


def test_html_is_rtl_for_arabic_and_escapes_markup():
    page = write_html("مرحباً\n\n<script>alert(1)</script>", "ar", "x").decode("utf-8")
    assert 'dir="rtl"' in page and 'lang="ar"' in page
    assert "<script>" not in page and "&lt;script&gt;" in page


def test_html_language_tags():
    assert 'lang="zh-Hans"' in write_html("你好", "zh").decode()
    assert 'dir="ltr"' in write_html("Bonjour", "fr").decode()


def test_html_splits_paragraphs():
    assert write_html("one\n\ntwo", "fr").decode().count("<p>") == 2


def test_output_stem():
    assert output_stem("/tmp/My Report.pdf", "fr") == "My Report.fr"
    assert output_stem("", "ja") == "translation.ja"
