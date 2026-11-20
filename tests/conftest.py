"""Shared test helpers: a fake Claude API (no network, no key) and a tiny PDF maker."""
import io
import re

import pytest

from translator import ClaudeClient, Glossary, TranslationService


class FakeTransport:
    """Pretends to be the Claude API. Echoes the text back as '<TargetName>text'.

    Records every request body in .bodies. Set truncate_over=N to make it reply 'cut off'
    for texts longer than N characters (to test the split-and-retry logic).
    """

    def __init__(self, detect="fr", truncate_over=None):
        self.bodies, self.detect, self.truncate_over = [], detect, truncate_over

    def __call__(self, body):
        self.bodies.append(body)
        content = body["messages"][0]["content"]
        if isinstance(content, list):                       # a PDF sent directly
            instruction, text = content[1]["text"], "<pdf>"
        else:
            instruction = content
            text = content.split("<text>\n", 1)[1].rsplit("\n</text>", 1)[0]
        target = re.search(r"into (.+?)\.", instruction).group(1)
        if self.truncate_over and len(text) > self.truncate_over:
            return {"stop_reason": "max_tokens", "content": []}
        return {"stop_reason": "tool_use", "content": [{
            "type": "tool_use", "name": "submit_translation",
            "input": {"source_language": self.detect, "translation": f"<{target}>{text}"}}]}


@pytest.fixture(scope="session")
def glossary():
    return Glossary.load()


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def service(glossary, transport):
    """A service wired to the fake API."""
    return TranslationService(glossary, ClaudeClient(api_key="test-key", transport=transport))


@pytest.fixture
def offline_service(glossary, monkeypatch):
    """A service with no API key at all."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return TranslationService(glossary, ClaudeClient())


def make_pdf(pages):
    """Build a real PDF. `pages` is a list of pages, each a list of text lines (needs reportlab)."""
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for lines in pages:
        y = 800
        for line in lines:
            c.drawString(50, y, line)
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()
