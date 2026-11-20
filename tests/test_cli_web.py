"""Tests for the command-line session and the web API."""
import io
import random
import time

import pytest

from cli import Session
from tests.conftest import FakeTransport, make_pdf
from translator import Chatbot, ClaudeClient, TranslationService, UnmatchedLog
from web.app import create_app


# ======================================================================== CLI
@pytest.fixture
def session(glossary, service, tmp_path):
    return Session(Chatbot(glossary, UnmatchedLog(tmp_path / "u.jsonl")), service, rng=random.Random(3))


def test_cli_translates_into_current_target(session):
    out = session.handle("Habari yako")
    assert out.splitlines()[0] == "[French -> French]" or out.startswith("[")      # header shows detected -> target
    assert "<French>Habari yako" in out


def test_cli_to_and_from(session):
    assert "Japanese" in session.handle("/to japanese")
    assert "Sheng" in session.handle("/to kenyan slang")
    assert "Unknown language" in session.handle("/to klingon")
    assert "German" in session.handle("/from german")
    assert "[German -> Sheng]" in session.handle("Guten Tag")
    assert "automatically" in session.handle("/from auto")
    assert "Unknown language" in session.handle("/from klingon")
    assert "auto-detect" in session.handle("/langs") and "Sheng" in session.handle("/langs")


def test_cli_shows_sheng_note_and_glossary_tip(session):
    out = session.handle("asante")
    assert "(glossary: 'asante'" in out
    session.handle("/to sheng")
    assert "(note: Sheng is informal" in session.handle("Hello")


def test_cli_without_ai_gives_helpful_message(glossary, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = Session(Chatbot(glossary), TranslationService(glossary, ClaudeClient()))
    assert "Merci beaucoup" in s.handle("asante")
    assert "ANTHROPIC_API_KEY" in s.handle("Habari yako, naomba msaada")


def test_cli_file_translation_writes_txt_and_html(session, tmp_path):
    src = tmp_path / "barua.txt"
    src.write_text("Habari yako rafiki.\n\nKaribu sana nyumbani.", encoding="utf-8")
    session.handle("/to ar")
    out = session.handle(f"/file {src}")
    assert "Translated barua.txt" in out
    txt, html_ = tmp_path / "barua.ar.txt", tmp_path / "barua.ar.html"
    assert "<Arabic>Habari yako rafiki." in txt.read_text(encoding="utf-8")
    assert 'dir="rtl"' in html_.read_text(encoding="utf-8")


def test_cli_file_errors_are_friendly(session, tmp_path):
    assert "Could not read" in session.handle(f"/file {tmp_path / 'missing.pdf'}")
    bad = tmp_path / "x.png"
    bad.write_bytes(b"x")
    assert "Unsupported file type" in session.handle(f"/file {bad}")
    assert "Use /file" in session.handle("/file")


def test_cli_define_list_help_quit(session):
    assert "Merci beaucoup" in session.handle("/define asante")
    assert "Use /define" in session.handle("/define")
    assert "mambo" in session.handle("/list sheng") and "asante" not in session.handle("/list sheng")
    assert "No category" in session.handle("/list nonsense")
    assert "/file" in session.handle("/help") and "sheng" in session.handle("/help").lower()
    assert session.handle("/quit") == "Kwaheri!" and session.done


def test_cli_unknown_command_blank_line_and_unmatched(session):
    assert "Unknown command" in session.handle("/dance")
    assert session.handle("") == ""
    assert session.handle("/unmatched") == "Nothing logged yet."
    session.handle("/define zzzzzz")
    assert "zzzzzz" in session.handle("/unmatched")


def test_cli_quiz_and_flashcards(session):
    session.handle("/to fr")
    assert "What is" in session.handle("/quiz")
    assert "Please answer" in session.handle("banana")
    out = session.handle("1")
    assert ("Correct!" in out or "Not quite" in out) and "What is" in out
    assert "Score:" in session.handle("q")
    session.handle("/to sheng")                                   # not a glossary language: quiz still works
    assert "What is" in session.handle("/quiz")
    session.handle("q")
    assert "[" in session.handle("/flash") and "Meaning" in session.handle("")
    assert "stopped" in session.handle("q")


# ======================================================================== web
@pytest.fixture
def client(service):
    return create_app(service).test_client()


def wait_for(client, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/files/{job_id}").get_json()
        if data["status"] != "running":
            return data
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def upload(client, content=b"Habari yako rafiki yangu.", name="note.txt", **fields):
    form = {"file": (io.BytesIO(content), name), "source": "auto", "target": "ar", **fields}
    return client.post("/api/files", data=form, content_type="multipart/form-data")


def test_index_page_lists_nine_languages(client):
    page = client.get("/").get_data(as_text=True)
    assert 'lang="en"' in page and "Karibu Translator" in page
    for name in ("Sheng", "Swahili", "Arabic", "Chinese (Simplified)", "German", "Detect language"):
        assert name in page
    assert "AI translation is off" not in page


def test_index_shows_banner_without_key(glossary, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    page = create_app(TranslationService(glossary, ClaudeClient())).test_client().get("/").get_data(as_text=True)
    assert "AI translation is off" in page


def test_api_translate_sentence_between_any_languages(client):
    r = client.post("/api/translate", json={"text": "Guten Morgen, wie geht es dir?", "source": "auto", "target": "ar"})
    d = r.get_json()
    assert r.status_code == 200 and d["engine"] == "claude"
    assert d["translation"].startswith("<Arabic>") and d["target_dir"] == "rtl" and d["target_lang"] == "ar"
    assert d["source"] == "fr" and d["source_name"] == "French"          # the fake API "detects" French


def test_api_translate_chinese_target_uses_hans_tag(client):
    d = client.post("/api/translate", json={"text": "hello", "target": "zh"}).get_json()
    assert d["target_lang"] == "zh-Hans" and d["target_dir"] == "ltr"


def test_api_translate_returns_glossary_tips(client):
    d = client.post("/api/translate", json={"text": "asante", "target": "ja"}).get_json()
    assert d["tips"][0]["term"] == "asante"


@pytest.mark.parametrize("payload, status", [
    ({}, 400), ({"text": "hi"}, 400), ({"text": "  ", "target": "fr"}, 400),
    ({"text": "hi", "target": "klingon"}, 400), ({"text": "hi", "target": "fr", "source": "klingon"}, 400),
    ({"text": "x" * 20001, "target": "fr"}, 400),
])
def test_api_translate_rejects_bad_input(client, payload, status):
    assert client.post("/api/translate", json=payload).status_code == status


def test_api_translate_without_key_explains(glossary, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = create_app(TranslationService(glossary, ClaudeClient())).test_client()
    ok = c.post("/api/translate", json={"text": "asante", "target": "fr"})
    assert ok.status_code == 200 and ok.get_json()["translation"] == "Merci beaucoup"
    nope = c.post("/api/translate", json={"text": "Habari yako, naomba msaada", "target": "fr"})
    assert nope.status_code == 503 and "ANTHROPIC_API_KEY" in nope.get_json()["error"]


def test_api_translate_reports_upstream_failure(glossary):
    def broken(body):
        raise __import__("translator").TranslationError("The Claude API key was rejected. Check ANTHROPIC_API_KEY.")
    c = create_app(TranslationService(glossary, ClaudeClient(api_key="k", transport=broken))).test_client()
    r = c.post("/api/translate", json={"text": "hello", "target": "fr"})
    assert r.status_code == 502 and "rejected" in r.get_json()["error"]


def test_file_job_flow_with_downloads(client):
    r = upload(client, b"Habari yako rafiki yangu.\n\nKaribu sana.", "barua.txt", target="ar")
    assert r.status_code == 200
    start = r.get_json()
    assert start["chunks"] == 1 and start["kind"] == "text"
    done = wait_for(client, start["job_id"])
    assert done["status"] == "done" and done["done"] == done["total"] == 1
    assert done["target_dir"] == "rtl" and "<Arabic>Habari yako rafiki yangu." in done["preview"]

    txt = client.get(f"/api/files/{start['job_id']}/download?format=txt")
    assert txt.status_code == 200 and "attachment" in txt.headers["Content-Disposition"]
    assert "barua.ar.txt" in txt.headers["Content-Disposition"]
    assert "<Arabic>Habari yako rafiki yangu." in txt.get_data(as_text=True)

    page = client.get(f"/api/files/{start['job_id']}/download?format=html").get_data(as_text=True)
    assert 'dir="rtl"' in page and "<p><Arabic>" not in page      # angle brackets are escaped
    assert client.get(f"/api/files/{start['job_id']}/download?format=pdf").status_code == 400


def test_pdf_upload_through_the_web(client):
    pytest.importorskip("pypdf")
    pdf = make_pdf([["This is the first line of a real PDF document with enough text in it.",
                     "And here is a second line that belongs to the same sentence."]])
    start = upload(client, pdf, "paper.pdf", target="fr").get_json()
    assert start["kind"] == "pdf-text" and start["pages"] == 1
    done = wait_for(client, start["job_id"])
    assert done["status"] == "done" and "first line of a real PDF" in done["preview"]


def test_file_upload_validation(client):
    assert upload(client, name="photo.png").status_code == 400
    assert upload(client, b"").status_code == 400
    assert upload(client, target="klingon").status_code == 400
    assert client.post("/api/files", data={"target": "fr"}, content_type="multipart/form-data").status_code == 400


def test_file_too_large_is_413(service):
    app = create_app(service)
    app.config["MAX_CONTENT_LENGTH"] = 200
    r = upload(app.test_client(), b"x" * 5000)
    assert r.status_code == 413 and "too large" in r.get_json()["error"]


def test_file_upload_without_key(glossary, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = create_app(TranslationService(glossary, ClaudeClient())).test_client()
    r = upload(c)
    assert r.status_code == 503 and "Claude API" in r.get_json()["error"]


def test_job_errors_surface_in_status(glossary):
    def fail(body):
        raise __import__("translator").TranslationError("The Claude API key was rejected.")
    c = create_app(TranslationService(glossary, ClaudeClient(api_key="k", transport=fail))).test_client()
    done = wait_for(c, upload(c).get_json()["job_id"])
    assert done["status"] == "error" and "rejected" in done["error"]


def test_unknown_job_and_unfinished_download(client):
    assert client.get("/api/files/nope").status_code == 404
    assert client.get("/api/files/nope/download").status_code == 404


def test_too_many_running_jobs_is_429(glossary):
    import threading
    gate = threading.Event()

    def slow(body):
        gate.wait(5)
        return FakeTransport()(body)
    c = create_app(TranslationService(glossary, ClaudeClient(api_key="k", transport=slow))).test_client()
    ids = [upload(c).get_json()["job_id"] for _ in range(3)]
    assert upload(c).status_code == 429
    gate.set()
    for job_id in ids:
        wait_for(c, job_id)


def test_languages_quiz_and_glossary_endpoints(client):
    d = client.get("/api/languages").get_json()
    assert [l["code"] for l in d["languages"]] == ["en", "sw", "sheng", "ar", "fr", "ja", "es", "zh", "de"] and d["ai_on"]
    q = client.get("/api/quiz?lang=ar").get_json()
    assert q["dir"] == "rtl" and len(q["options"]) == 4
    assert client.get("/api/quiz?lang=all").status_code == 400
    assert client.get("/api/quiz?lang=sheng").status_code == 400
    assert client.get("/api/quiz?lang=fr&category=nope").status_code == 400
    assert len(client.get("/api/glossary").get_json()) >= 60
