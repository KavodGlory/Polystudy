"""Reading files (PDF, TXT, MD), splitting long text into chunks, and writing results.

Why chunks? The Claude API answers a limited amount of text per request. A long document is
cut into pieces of about 3,000 characters at paragraph (or sentence) boundaries, each piece
is translated, and the pieces are joined back together in order.
"""
from __future__ import annotations

import html
import io
import os
import re
import shutil
import subprocess
import tempfile

from .errors import DocumentError
from .languages import LANGUAGES

CHUNK_CHARS = 3000
SUPPORTED_EXTENSIONS = (".pdf", ".txt", ".md")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？؟])\s+")
_SENTENCE_END = re.compile(r"[.!?:;。！？؟”\")]$")


def _is_cjk(ch: str) -> bool:
    return ord(ch) > 0x2E80


# ------------------------------------------------------------------ reading
def decode_text(data: bytes) -> str:
    """Decode a text file: UTF-8 (with or without BOM), UTF-16 with BOM, else Latin-1."""
    text = None
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            text = data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    if text is None:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def reflow(text: str) -> str:
    """Repair the hard line breaks PDFs put in the middle of sentences.

    A PDF stores each printed line separately: "...the quick brown\\nfox jumps...". We join such
    lines back into paragraphs, but keep short lines (headings, list items) on their own line.
    """
    out: list[str] = []
    buf = ""
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            if buf:
                out.append(buf)
                buf = ""
            out.append("")
        elif not buf:
            buf = line
        elif buf.endswith("-") and line[:1].islower():          # "infor-\nmation"
            buf = buf[:-1] + line
        elif len(buf) >= (18 if _is_cjk(buf[-1]) else 45) and not _SENTENCE_END.search(buf):  # sentence continues
            # (a CJK line holds far fewer characters than a Latin one, hence the lower threshold)
            glue = "" if _is_cjk(buf[-1]) and _is_cjk(line[0]) else " "
            buf += glue + line
        else:
            out.append(buf)
            buf = line
    if buf:
        out.append(buf)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _pdf_with_pypdf(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader  # ImportError is handled by the caller
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")
        except Exception:
            ok = 0
        if not ok:
            raise DocumentError("This PDF is password protected. Remove the password and try again.")
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n\n".join(pages), len(pages)


def _pdf_with_pdftotext(data: bytes) -> tuple[str, int]:
    exe = shutil.which("pdftotext")
    if not exe:
        raise DocumentError("Reading PDFs needs the 'pypdf' package. Install it with: pip install pypdf")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "in.pdf")
        with open(path, "wb") as f:
            f.write(data)
        result = subprocess.run([exe, "-enc", "UTF-8", path, "-"], capture_output=True, timeout=120)
    if result.returncode != 0:
        raise DocumentError("Could not read this PDF. It may be damaged or password protected.")
    text = result.stdout.decode("utf-8", errors="replace")
    return text, text.count("\f") or 1


def extract_pdf_text(data: bytes) -> tuple[str, int]:
    """Return (text, page_count). The text is empty for scanned (image-only) PDFs."""
    try:
        text, pages = _pdf_with_pypdf(data)
    except ImportError:
        text, pages = _pdf_with_pdftotext(data)
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError("Could not read this PDF. It may be damaged.") from exc
    return reflow(text), pages


# ------------------------------------------------------------------ chunking
def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """Split one very long paragraph at sentence ends (hard-cutting only as a last resort)."""
    pieces: list[str] = []
    cur = ""
    for sentence in _SENTENCE_SPLIT.split(paragraph):
        while len(sentence) > max_chars:                     # one gigantic sentence
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(sentence[:cut].rstrip())
            sentence = sentence[cut:].lstrip()
        if cur and len(cur) + 1 + len(sentence) > max_chars:
            pieces.append(cur)
            cur = sentence
        else:
            cur = f"{cur} {sentence}" if cur else sentence
    if cur:
        pieces.append(cur)
    return pieces


def chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> list[tuple[str, str]]:
    """Split text into [(chunk, separator_that_follows)], each chunk at most max_chars long.

    Joining "".join(chunk + separator) rebuilds the text with paragraphs intact.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    units: list[tuple[str, str]] = []
    for p in paragraphs:
        if len(p) <= max_chars:
            units.append((p, "\n\n"))
        else:
            parts = _split_long_paragraph(p, max_chars)
            units += [(part, " " if i < len(parts) - 1 else "\n\n") for i, part in enumerate(parts)]

    chunks: list[tuple[str, str]] = []
    cur, cur_sep = None, ""
    for piece, sep in units:
        if cur is None:
            cur, cur_sep = piece, sep
        elif len(cur) + len(cur_sep) + len(piece) <= max_chars:
            cur, cur_sep = cur + cur_sep + piece, sep
        else:
            chunks.append((cur, cur_sep))
            cur, cur_sep = piece, sep
    if cur is not None:
        chunks.append((cur, ""))
    return chunks


# ------------------------------------------------------------------ writing
def output_stem(filename: str, target: str) -> str:
    """'report.pdf' + 'fr' -> 'report.fr'"""
    stem = os.path.splitext(os.path.basename(filename))[0] or "translation"
    return f"{stem}.{target}"


def write_txt(text: str) -> bytes:
    return text.encode("utf-8")


def write_html(text: str, target: str, title: str = "Translation") -> bytes:
    """A standalone page that shows Arabic right-to-left and picks proper CJK fonts.

    Open it in a browser and use Print > Save as PDF to get a PDF.
    """
    lang = LANGUAGES[target]
    paragraphs = "\n".join(f"<p>{html.escape(p.strip())}</p>"
                           for p in re.split(r"\n\s*\n", text.strip()) if p.strip())
    page = f"""<!doctype html>
<html lang="{lang.html_lang}" dir="{'rtl' if lang.rtl else 'ltr'}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  body {{ max-width: 42em; margin: 2em auto; padding: 0 1em; color: #1d2320; background: #fff;
         font: 1.05em/1.75 system-ui, "Segoe UI", "Noto Sans", "Noto Naskh Arabic", "Noto Sans JP", "Noto Sans SC", sans-serif; }}
  p {{ margin: 0 0 1em; white-space: pre-line; }}
  footer {{ margin-top: 2em; color: #666; font-size: .8em; }}
</style>
</head>
<body>
{paragraphs}
<footer>Machine translation by Claude. Have important documents checked by a qualified translator.</footer>
</body>
</html>
"""
    return page.encode("utf-8")
