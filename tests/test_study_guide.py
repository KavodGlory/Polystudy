from types import SimpleNamespace

import pytest

from study_guide.app import app
from study_guide.integrations import JotformClient, IntegrationError, SupabaseClient


@pytest.fixture
def client():
    app.config.update(TESTING=True)
    return app.test_client()


def test_health_route_and_html_cache_headers(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.get_json()["status"] == "ok"
    home = client.get("/")
    assert home.status_code == 200
    assert "no-store" in home.headers["Cache-Control"]


def test_favicon_route_redirects_to_svg(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/static/favicon.svg")


def test_unknown_api_route_returns_json(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.get_json()["error"]

def test_student_pages_render(client):
    for path in ("/", "/translator", "/notes", "/quiz", "/help", "/resources"):
        response = client.get(path)
        assert response.status_code == 200
        assert b"POLYSTUDY" in response.data


def test_quiz_endpoint_returns_localized_bilingual_questions(client):
    english = client.get("/api/quizzes?language=en").get_json()["quizzes"]
    swahili = client.get("/api/quizzes?language=sw").get_json()["quizzes"]
    assert len(english) >= 3
    assert english[0]["question"] != swahili[0]["question"]
    assert len(english[0]["choices"]) == 4
    assert english[0]["choices"][english[0]["answer_index"]]
    assert client.get("/api/quizzes?language=fr").status_code == 400


def test_help_desk_uses_supabase_glossary(client):
    payload = client.get("/api/university-info?language=sw").get_json()
    assert payload["source"] == "Supabase"
    assert payload["items"]
    assert all(item["institution"] == "Supabase" for item in payload["items"])
    assert all(item["title"] and item["body"] for item in payload["items"])


def test_quiz_generator_creates_nonrepeating_multi_question_sessions(client):
    response = client.post(
        "/api/quizzes/generate",
        json={"language": "sw", "subject": "all", "count": 5},
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["count"] == len(payload["questions"]) == 5
    assert len({question["id"] for question in payload["questions"]}) == 5
    assert all(question["question"] and len(question["choices"]) == 4 for question in payload["questions"])


def test_quiz_generator_validates_count_and_subject_availability(client):
    assert client.post("/api/quizzes/generate", json={"count": 13}).status_code == 400
    assert client.post(
        "/api/quizzes/generate",
        json={"subject": "Digital literacy", "count": 12},
    ).status_code == 400


def test_jotform_client_uses_server_header_and_reads_form_metadata(monkeypatch):
    import json
    import study_guide.integrations as integrations

    integrations._jotform_cache.clear()
    calls = []

    class Response:
        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.value).encode()

    def fake_urlopen(request, timeout):
        calls.append(request)
        if request.full_url.endswith("/questions"):
            return Response({"responseCode": 200, "content": {
                "1": {"type": "control_radio", "text": "Question one"},
                "2": {"type": "control_textbox", "text": "Question two"},
            }})
        return Response({"responseCode": 200, "content": {"title": "Quiz form"}})

    monkeypatch.setattr(integrations.urllib.request, "urlopen", fake_urlopen)
    summary = JotformClient(
        api_key="test-key",
        form_id="263230744199057",
    ).form_summary(force_refresh=True)
    assert summary["title"] == "Quiz form" and summary["question_count"] == 2
    assert summary["questions"] == ["Question one", "Question two"]
    assert all("test-key" not in request.full_url for request in calls)
    assert all(request.get_header("Apikey") == "test-key" for request in calls)


def test_jotform_auth_failure_is_reported_without_secret(monkeypatch):
    import urllib.error
    import study_guide.integrations as integrations

    def unauthorized(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(integrations.urllib.request, "urlopen", unauthorized)
    with pytest.raises(IntegrationError, match="rejected"):
        JotformClient(api_key="secret", form_id="263230744199057").form_summary(force_refresh=True)


def test_jotform_route_reports_unconfigured_api_without_exposing_credentials(client, monkeypatch):
    monkeypatch.delenv("JOTFORM_API_KEY", raising=False)
    response = client.get("/api/jotform/form")
    assert response.status_code == 200
    assert response.get_json()["connected"] is False
    assert "JOTFORM_API_KEY" in response.get_json()["error"]
    assert response.get_json()["form_url"] == "https://form.jotform.com/263230744199057"


def test_jotform_invalid_form_id_is_not_reported_as_missing_key(monkeypatch):
    client = JotformClient(api_key="test-key", form_id="not-numeric")
    assert client.configured is False
    assert "JOTFORM_QUIZ_FORM_ID" in client.configuration_error


def test_supabase_glossary_reads_exact_columns(monkeypatch):
    import json
    import study_guide.integrations as integrations

    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps([
                {"id": 1, "term_en": "house", "term_translated": "maison", "language": "French"}
            ]).encode()

    def fake_urlopen(request, timeout):
        calls.append(request)
        return Response()

    monkeypatch.setattr(integrations.urllib.request, "urlopen", fake_urlopen)
    client = SupabaseClient(
        url="https://example.supabase.co",
        api_key="test-publishable-key",
    )
    entries = client.list_glossary(language="French")
    assert entries[0]["term_translated"] == "maison"
    assert "language=eq.French" in calls[0].full_url
    assert calls[0].get_header("Apikey") == "test-publishable-key"
    assert calls[0].get_header("Authorization") == "Bearer test-publishable-key"


def test_supabase_quiz_result_validates_score(monkeypatch):
    client = SupabaseClient(
        url="https://example.supabase.co",
        api_key="test-publishable-key",
    )
    with pytest.raises(ValueError, match="0 and 100"):
        client.save_quiz_result(-1)
    with pytest.raises(ValueError, match="0 and 100"):
        client.save_quiz_result(True)


def test_supabase_client_has_project_defaults(monkeypatch):
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    assert SupabaseClient().configured is True


def test_jotform_rejects_non_object_api_response(monkeypatch):
    import study_guide.integrations as integrations

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"[]"

    monkeypatch.setattr(integrations.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(IntegrationError, match="unexpected response"):
        JotformClient(api_key="test-key", form_id="263230744199057")._get("/user")


def test_library_route_validates_and_returns_openalex_source(client, monkeypatch):
    def fake_search(query):
        if not query:
            raise ValueError("Enter a research topic between 2 and 200 characters.")
        return [{"title": query}]

    monkeypatch.setattr("study_guide.app.search_open_access_works", fake_search)
    response = client.get("/api/library?query=climate")
    assert response.status_code == 200
    assert response.get_json()["source"] == "OpenAlex"
    assert response.get_json()["results"] == [{"title": "climate"}]
    assert client.get("/api/library?query=").status_code == 400


def test_openalex_search_returns_only_open_access_records_and_caches(monkeypatch, tmp_path):
    import json
    import study_guide.integrations as integrations
    import sqlite3

    cache_path = tmp_path / "research.db"
    with sqlite3.connect(cache_path) as con:
        con.execute(
            "CREATE TABLE research_cache "
            "(query TEXT, result_limit INTEGER, fetched_at REAL, results_json TEXT, "
            "PRIMARY KEY (query, result_limit))"
        )
    monkeypatch.setattr(integrations, "DB_PATH", cache_path)
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"results": [
                {"title": "Open article", "publication_year": 2024,
                 "authorships": [{"author": {"display_name": "A. Author"}}],
                 "primary_location": {"source": {"display_name": "Journal"},
                                      "landing_page_url": "https://example.org/article"},
                 "open_access": {"is_oa": True, "oa_url": "https://example.org/article"}},
                {"title": "Closed article", "open_access": {"is_oa": False}},
            ]}).encode()

    def fake_urlopen(request, timeout):
        calls.append(request)
        return Response()

    monkeypatch.setattr(integrations.urllib.request, "urlopen", fake_urlopen)
    first = integrations.search_open_access_works("  public   health ")
    second = integrations.search_open_access_works("public health")
    assert first == second and len(first) == 1
    assert first[0]["authors"] == ["A. Author"] and len(calls) == 1
    assert "open_access.is_oa%3Atrue" in calls[0].full_url


def test_text_translation_uses_existing_service(client, monkeypatch):
    class FakeService:
        def translate_text(self, text, target, source):
            return SimpleNamespace(
                text=f"{target}:{text}",
                source="en",
                target=target,
                engine="fake",
                notes=[],
            )

    monkeypatch.setattr("study_guide.app.get_service", lambda: FakeService())
    response = client.post(
        "/api/translate",
        json={"text": "study", "source": "en", "target": "sw"},
    )
    assert response.status_code == 200
    assert response.get_json()["translation"] == "sw:study"


def test_translation_rejects_empty_text_and_unknown_languages(client):
    assert client.post("/api/translate", json={"text": "", "target": "en"}).status_code == 400
    assert client.post(
        "/api/translate",
        json={"text": "hello", "source": "en", "target": "not-a-language"},
    ).status_code == 400


def test_document_translation_reuses_translation_service(client, monkeypatch):
    class FakeService:
        ai_available = True

        def translate_document(self, data, filename, target, source):
            assert data == b"sample class notes"
            assert filename.endswith(".txt")
            return SimpleNamespace(
                text="maelezo ya darasa",
                filename=filename,
                source="en",
                target=target,
                chunks=1,
            )

    monkeypatch.setattr("study_guide.app.get_service", lambda: FakeService())
    response = client.post(
        "/api/document",
        data={
            "source": "en",
            "target": "sw",
            "file": (pytest.importorskip("io").BytesIO(b"sample class notes"), "notes.txt"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert response.get_json()["translation"] == "maelezo ya darasa"
