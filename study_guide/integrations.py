"""Server-side integrations for Jotform and open-access research metadata."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse

from .db import DB_PATH

DEFAULT_JOTFORM_FORM_ID = "263230744199057"
JOTFORM_API_BASE = "https://api.jotform.com"
OPENALEX_API = "https://api.openalex.org/works"
OPENALEX_CACHE_SECONDS = 6 * 60 * 60
JOTFORM_CACHE_SECONDS = 10 * 60
DEFAULT_SUPABASE_URL = "https://ozqompzquetevyanjqqf.supabase.co"
DEFAULT_SUPABASE_KEY = "sb_publishable_7_9o_2hJ5kiGF7nRlr7rBw_bzf5u2XX"


class IntegrationError(Exception):
    """An external service could not provide usable data."""


_jotform_cache: dict[str, tuple[float, dict]] = {}


class SupabaseClient:
    """Read and write the teammate's Supabase glossary and quiz tables."""

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        timeout: int = 10,
    ):
        self.url = (url or os.environ.get("SUPABASE_URL", DEFAULT_SUPABASE_URL)).strip().rstrip("/")
        self.api_key = (
            api_key
            if api_key is not None
            else (
                os.environ.get("SUPABASE_ANON_KEY")
                or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
                or os.environ.get("SUPABASE_KEY")
                or DEFAULT_SUPABASE_KEY
            )
        ).strip()
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        try:
            parsed = urlparse(self.url)
        except ValueError:
            return False
        return bool(
            parsed.scheme == "https"
            and parsed.netloc
            and self.api_key
        )

    @property
    def configuration_error(self) -> str:
        if not self.api_key:
            return "Set SUPABASE_ANON_KEY or SUPABASE_PUBLISHABLE_KEY on the server."
        if not self.url or not re.fullmatch(r"https://[A-Za-z0-9.-]+(?:/[A-Za-z0-9.-]*)*", self.url):
            return "Set SUPABASE_URL to a valid HTTPS Supabase project URL."
        return ""

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def _request(self, path: str, method: str = "GET", payload: dict | None = None) -> object:
        if not self.configured:
            raise IntegrationError(self.configuration_error)
        candidates = [self.url]
        if self.url.endswith(".supabase.com"):
            candidates.append(self.url.replace(".supabase.com", ".supabase.co"))
        raw = None
        last_unavailable = None
        for candidate in candidates:
            body = None
            headers = self._headers()
            if payload is not None:
                body = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"
                headers["Prefer"] = "return=representation"
            request = urllib.request.Request(
                f"{candidate}{path}",
                data=body,
                headers=headers,
                method=method,
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    self.url = candidate
                    break
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise IntegrationError("Supabase rejected the API key. Replace the configured Supabase key.") from exc
                raise IntegrationError(f"Supabase returned an error ({exc.code}).") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_unavailable = exc
        if raw is None:
            raise IntegrationError("Supabase could not be reached. Try again shortly.") from last_unavailable
        if not raw:
            return []
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IntegrationError("Supabase returned an invalid response.") from exc

    def list_glossary(self, language: str | None = None, limit: int = 100) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Choose a glossary limit between 1 and 500.")
        params = {
            "select": "id,term_en,term_translated,language",
            "limit": str(limit),
            "order": "id.asc",
        }
        if language:
            language = language.strip()
            if not language or len(language) > 50:
                raise ValueError("Choose a valid glossary language.")
            params["language"] = f"eq.{language}"
        data = self._request(f"/rest/v1/glossary?{urllib.parse.urlencode(params)}")
        if not isinstance(data, list):
            raise IntegrationError("Supabase returned an unexpected glossary response.")
        return [
            {
                "id": row.get("id"),
                "term_en": row.get("term_en"),
                "term_translated": row.get("term_translated"),
                "language": row.get("language"),
            }
            for row in data
            if isinstance(row, dict)
        ]

    def save_quiz_result(self, score: int) -> dict:
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            raise ValueError("Quiz score must be an integer between 0 and 100.")
        data = self._request("/rest/v1/quiz_results", "POST", {"score": score})
        if isinstance(data, list) and data:
            return data[0] if isinstance(data[0], dict) else {"score": score}
        return {"score": score}


def configured_jotform_form_id() -> str:
    form_id = os.environ.get("JOTFORM_QUIZ_FORM_ID", DEFAULT_JOTFORM_FORM_ID).strip()
    return form_id if re.fullmatch(r"\d{6,20}", form_id) else ""


class JotformClient:
    def __init__(self, api_key: str | None = None, form_id: str | None = None, timeout: int = 10):
        self.api_key = api_key if api_key is not None else os.environ.get("JOTFORM_API_KEY", "")
        self.form_id = form_id or configured_jotform_form_id()
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.form_id and re.fullmatch(r"\d{6,20}", self.form_id))

    @property
    def configuration_error(self) -> str | None:
        if not self.api_key:
            return "Set JOTFORM_API_KEY on the server to connect the quiz form."
        if not self.form_id or not re.fullmatch(r"\d{6,20}", self.form_id):
            return "Set JOTFORM_QUIZ_FORM_ID to a valid numeric form ID."
        return None

    @property
    def form_url(self) -> str | None:
        if not self.form_id or not re.fullmatch(r"\d{6,20}", self.form_id):
            return None
        return f"https://form.jotform.com/{self.form_id}"

    def _get(self, path: str) -> dict:
        request = urllib.request.Request(
            f"{JOTFORM_API_BASE}{path}",
            headers={"APIKEY": self.api_key, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except json.JSONDecodeError as exc:
            raise IntegrationError("Jotform returned an invalid response.") from exc
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise IntegrationError("Jotform rejected the API key. Replace JOTFORM_API_KEY and try again.") from exc
            raise IntegrationError(f"Jotform returned an error ({exc.code}).") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise IntegrationError("Jotform could not be reached. Try again shortly.") from exc
        if not isinstance(data, dict):
            raise IntegrationError("Jotform returned an unexpected response.")
        if data.get("responseCode") not in (None, 200):
            raise IntegrationError(f"Jotform returned an error ({data.get('responseCode')}).")
        return data

    def form_summary(self, force_refresh: bool = False) -> dict:
        if not self.configured:
            raise IntegrationError(self.configuration_error or "Jotform is not configured.")
        now = time.time()
        cached = _jotform_cache.get(self.form_id)
        if cached and cached[0] > now and not force_refresh:
            return dict(cached[1])

        form_data = self._get(f"/form/{self.form_id}")
        questions_data = self._get(f"/form/{self.form_id}/questions")
        form = form_data.get("content") or {}
        questions = questions_data.get("content") or {}
        if not isinstance(form, dict) or not isinstance(questions, dict):
            raise IntegrationError("Jotform returned an unexpected form structure.")
        question_labels = [
            str(field["text"]).strip()[:300]
            for field in questions.values()
            if isinstance(field, dict)
            and field.get("text")
            and str(field.get("type", "")).startswith("control_")
        ][:20]
        summary = {
            "title": str(form.get("title") or "Jotform quiz"),
            "form_id": self.form_id,
            "form_url": self.form_url,
            "question_count": len(question_labels),
            "questions": question_labels,
            "source": "Jotform",
        }
        _jotform_cache[self.form_id] = (now + JOTFORM_CACHE_SECONDS, summary)
        return dict(summary)


def _safe_http_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return value


def _openalex_cache(query: str, limit: int) -> list[dict] | None:
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT fetched_at, results_json FROM research_cache WHERE query = ? AND result_limit = ?",
            (query, limit),
        ).fetchone()
    if not row or time.time() - row[0] >= OPENALEX_CACHE_SECONDS:
        return None
    try:
        results = json.loads(row[1])
    except json.JSONDecodeError:
        return None
    if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
        return None
    return results


def _save_openalex_cache(query: str, limit: int, results: list[dict]) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT OR REPLACE INTO research_cache (query, result_limit, fetched_at, results_json) "
            "VALUES (?, ?, ?, ?)",
            (query, limit, time.time(), json.dumps(results, ensure_ascii=False)),
        )
        con.commit()


def search_open_access_works(query: str, limit: int = 10) -> list[dict]:
    query = " ".join(query.split())
    if not 2 <= len(query) <= 200:
        raise ValueError("Enter a research topic between 2 and 200 characters.")
    if not 1 <= limit <= 20:
        raise ValueError("Choose between 1 and 20 results.")
    normalized_query = query.casefold()
    cached = _openalex_cache(normalized_query, limit)
    if cached is not None:
        return cached

    params = urllib.parse.urlencode({
        "search": query,
        "filter": "open_access.is_oa:true",
        "per-page": limit,
        "select": "id,title,publication_year,authorships,primary_location,open_access,doi",
    })
    request = urllib.request.Request(
        f"{OPENALEX_API}?{params}",
        headers={"Accept": "application/json", "User-Agent": "POLYSTUDY/1.0 (open-access research search)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.load(response)
    except json.JSONDecodeError as exc:
        raise IntegrationError("OpenAlex returned an invalid response.") from exc
    except urllib.error.HTTPError as exc:
        raise IntegrationError(f"OpenAlex returned an error ({exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IntegrationError("The research catalog could not be reached. Try again shortly.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise IntegrationError("OpenAlex returned an unexpected response.")

    results = []
    for work in payload.get("results", []):
        if not isinstance(work, dict):
            continue
        location = work.get("primary_location") or {}
        open_access = work.get("open_access") or {}
        if not isinstance(location, dict):
            location = {}
        if not isinstance(open_access, dict):
            open_access = {}
        source = location.get("source") or {}
        if not isinstance(source, dict):
            source = {}
        title = work.get("title")
        url = (_safe_http_url(open_access.get("oa_url"))
               or _safe_http_url(location.get("pdf_url"))
               or _safe_http_url(location.get("landing_page_url")))
        if not isinstance(title, str) or not title.strip() or not url or not open_access.get("is_oa"):
            continue
        authorships = work.get("authorships")
        if not isinstance(authorships, list):
            authorships = []
        authors = [
            author.get("author", {}).get("display_name")
            for author in authorships
            if isinstance(author, dict)
            and isinstance(author.get("author"), dict)
            and isinstance(author["author"].get("display_name"), str)
        ]
        results.append({
            "title": title.strip(),
            "authors": authors[:4],
            "year": work.get("publication_year"),
            "journal": (source.get("display_name") if source else None),
            "url": url,
            "doi": work.get("doi"),
            "is_open_access": True,
        })
    _save_openalex_cache(normalized_query, limit, results)
    return results
