"""Web interface (Flask). Run from the project folder:

    python3 -m web.app                  # then open http://127.0.0.1:5000
    flask --app web.app run             # same thing

Routes
    GET  /                          the page
    POST /api/translate             {text, source, target}  -> translation of a word/sentence/paragraphs
    POST /api/files                 multipart: file, source, target -> starts a background job
    GET  /api/files/<id>            job progress (and a preview when finished)
    GET  /api/files/<id>/download   ?format=txt|html
    GET  /api/languages, /api/quiz, /api/glossary
"""
from __future__ import annotations

import io
import random

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from translator import (LANGS, ClaudeClient, DocumentError, Glossary, LANGUAGES, NoEngineError,
                        TranslationError, TranslationService, language_list, make_question,
                        resolve_language, resolve_langs, resolve_source)
from translator.gemini_api import GeminiClient
from translator.documents import output_stem, write_html, write_txt

from .jobs import JobStore, TooBusy

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
PREVIEW_CHARS = 1500


def _pick_client():
    """Return the best available AI client.

    Priority order:
      1. Google Gemini  (GEMINI_API_KEY)  — free tier at aistudio.google.com
      2. Anthropic Claude (ANTHROPIC_API_KEY) — paid, from console.anthropic.com
      3. No client       — offline glossary-only mode

    Set only one key; both can coexist if you want a manual fallback later.
    """
    import os
    if os.environ.get("GEMINI_API_KEY"):
        return GeminiClient()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeClient()
    return None   # offline mode: glossary only


def default_service() -> TranslationService:
    return TranslationService(Glossary.load(), _pick_client())


def create_app(service: TranslationService | None = None) -> Flask:
    # Backward-compatible API used by older integrations and tests.
    if isinstance(service, __import__("translator").Chatbot):
        bot = service
        app = Flask(__name__)
        app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

        @app.errorhandler(413)
        def legacy_too_large(_):
            return jsonify(error="That file is too large."), 413

        @app.get("/")
        def legacy_index():
            return render_template("index.html", langs=language_list(),
                                   ai_on=getattr(bot, "llm", None) is not None,
                                   count=len(bot.glossary.entries),
                                   max_mb=MAX_UPLOAD_BYTES // (1024 * 1024))

        @app.post("/api/translate")
        def legacy_translate():
            data = request.get_json(silent=True) or {}
            text = str(data.get("text", "")).strip()
            if not text or len(text) > 500:
                return jsonify(error="Invalid text."), 400
            raw_langs = data.get("langs")
            langs = resolve_langs("all" if raw_langs == "all" else
                                  " ".join(raw_langs) if isinstance(raw_langs, list) else
                                  str(raw_langs or ""))
            if raw_langs is not None and langs is None:
                return jsonify(error="Unknown language."), 400
            reply = bot.respond(text, langs)
            if reply.status == "llm":
                return jsonify(status="llm", llm={"text": reply.llm_text, "unverified": True})
            if reply.status == "none":
                return jsonify(status="none")
            langs = langs or list(LANGS)
            results = []
            for m in reply.matches:
                e = m.entry
                translations = []
                if reply.status == "reverse":
                    entry = {"typed_language": LANGS[m.lang],
                             "say": e["aliases"][0],
                             "meaning": e["meaning"]}
                else:
                    entry = {"typed_language": "English"}
                    translations = [
                        {"code": code, "text": e["translations"][code],
                         "dir": "rtl" if LANGUAGES[code].rtl else "ltr"}
                        for code in langs
                    ]
                results.append(dict(entry, translations=translations))
            return jsonify(status=reply.status, results=results)

        @app.get("/api/quiz")
        def legacy_quiz():
            langs = resolve_langs(request.args.get("lang", "fr"))
            if not langs or len(langs) != 1:
                return jsonify(error="Choose exactly one language."), 400
            category = request.args.get("category")
            if category and category not in bot.glossary.categories():
                return jsonify(error="Unknown category."), 400
            q = make_question(bot.glossary, langs[0], random.Random(), category=category)
            return jsonify(term=q.term, meaning=q.meaning, language=LANGS[q.lang],
                           code=q.lang, dir="rtl" if LANGUAGES[q.lang].rtl else "ltr",
                           html_lang=LANGUAGES[q.lang].html_lang,
                           options=q.options, answer_index=q.answer_index)

        @app.get("/api/glossary")
        def legacy_glossary():
            return jsonify([{"term": e["aliases"][0], "category": e["category"],
                             "register": e["register"], "meaning": e["meaning"],
                             "needs_review": e["needs_review"]} for e in bot.glossary.entries])

        return app

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    service = service or default_service()
    glossary = service.glossary
    jobs = JobStore()

    def error(message: str, status: int):
        return jsonify(error=message), status

    def read_languages(data) -> tuple[str | None, str | None]:
        """Pull (source, target) out of a JSON body or form. Returns codes, or None when invalid."""
        source = resolve_source(data.get("source"))
        target = resolve_language(data.get("target"))
        return source, target

    @app.errorhandler(413)
    def too_large(_):
        return error(f"That file is too large. The limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.", 413)

    # ------------------------------------------------------------------ pages
    @app.get("/")
    def index():
        return render_template("index.html", langs=language_list(), ai_on=service.ai_available,
                               count=len(glossary.entries), max_mb=MAX_UPLOAD_BYTES // (1024 * 1024))

    @app.get("/api/languages")
    def languages():
        return jsonify(languages=language_list(), ai_on=service.ai_available)

    # -------------------------------------------------------------- translate
    @app.post("/api/translate")
    def translate():
        data = request.get_json(silent=True) or {}
        source, target = read_languages(data)
        if target is None:
            return error("Please choose a language to translate into.", 400)
        if source is None:
            return error("Unknown source language.", 400)
        try:
            result = service.translate_text(str(data.get("text", "")), target, None if source == "auto" else source)
        except ValueError as exc:
            return error(str(exc), 400)
        except NoEngineError as exc:
            return error(str(exc), 503)
        except TranslationError as exc:
            return error(str(exc), 502)
        t = LANGUAGES[result.target]
        s = LANGUAGES.get(result.source)
        return jsonify(translation=result.text, engine=result.engine, notes=result.notes, tips=result.tips,
                       source=result.source, source_name=s.name if s else "an unrecognised language",
                       target=result.target, target_name=t.name, target_dir="rtl" if t.rtl else "ltr",
                       target_lang=t.html_lang)

    # ------------------------------------------------------------------ files
    @app.post("/api/files")
    def upload():
        upload_ = request.files.get("file")
        if upload_ is None or not upload_.filename:
            return error("Please choose a file.", 400)
        source, target = read_languages(request.form)
        if target is None:
            return error("Please choose a language to translate into.", 400)
        if source is None:
            return error("Unknown source language.", 400)
        src = None if source == "auto" else source
        try:
            prepared = service.prepare_document(upload_.read(), upload_.filename)
        except DocumentError as exc:
            return error(str(exc), 400)
        if not service.ai_available:
            return error("Translating files needs the Claude API. Set the ANTHROPIC_API_KEY environment "
                         "variable and restart the server.", 503)
        total = max(len(prepared.chunks), 1)
        try:
            job_id = jobs.start(lambda progress: service.translate_prepared(prepared, target, src, progress),
                                upload_.filename, target, total)
        except TooBusy as exc:
            return error(str(exc), 429)
        return jsonify(job_id=job_id, chunks=total, characters=prepared.characters, kind=prepared.kind,
                       pages=prepared.pages)

    @app.get("/api/files/<job_id>")
    def job_status(job_id):
        job = jobs.get(job_id)
        if job is None:
            return error("That job was not found. It may have expired.", 404)
        out = {"status": job.status, "done": job.done, "total": job.total, "filename": job.filename}
        if job.status == "error":
            out["error"] = job.error
        if job.status == "done":
            r, t = job.result, LANGUAGES[job.target]
            s = LANGUAGES.get(r.source)
            out.update(preview=r.text[:PREVIEW_CHARS], truncated=len(r.text) > PREVIEW_CHARS, notes=r.notes,
                       source_name=s.name if s else "an unrecognised language", target_name=t.name,
                       target_dir="rtl" if t.rtl else "ltr", target_lang=t.html_lang)
        return jsonify(out)

    @app.get("/api/files/<job_id>/download")
    def download(job_id):
        job = jobs.get(job_id)
        if job is None or job.status != "done":
            return error("That translation is not available.", 404)
        fmt = request.args.get("format", "txt")
        if fmt not in ("txt", "html"):
            return error("Format must be txt or html.", 400)
        stem = secure_filename(output_stem(job.filename, job.target)) or f"translation.{job.target}"
        if fmt == "txt":
            payload, mime = write_txt(job.result.text), "text/plain; charset=utf-8"
        else:
            payload, mime = write_html(job.result.text, job.target, stem), "text/html; charset=utf-8"
        return send_file(io.BytesIO(payload), mimetype=mime, as_attachment=True, download_name=f"{stem}.{fmt}")

    # ------------------------------------------------- glossary-based practice
    @app.get("/api/quiz")
    def quiz():
        langs = resolve_langs(request.args.get("lang", "fr"))
        if not langs or len(langs) != 1:
            return error("Choose exactly one language for the quiz.", 400)
        category = request.args.get("category") or None
        if category and category not in glossary.categories():
            return error("Unknown category.", 400)
        q = make_question(glossary, langs[0], random.Random(), category=category)
        return jsonify(term=q.term, meaning=q.meaning, language=LANGS[q.lang], code=q.lang,
                       dir="rtl" if LANGUAGES[q.lang].rtl else "ltr", html_lang=LANGUAGES[q.lang].html_lang,
                       options=q.options, answer_index=q.answer_index)

    @app.get("/api/glossary")
    def glossary_list():
        return jsonify([{"term": e["aliases"][0], "category": e["category"], "register": e["register"],
                         "meaning": e["meaning"], "needs_review": e["needs_review"]}
                        for e in glossary.entries])

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
