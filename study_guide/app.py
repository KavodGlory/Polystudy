"""POLYSTUDY student portal, using the existing Karibu translation service."""
import os
import random

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from translator.errors import DocumentError, NoEngineError, TranslationError
from translator.languages import LANGUAGES, language_list, resolve_language, resolve_source

from . import db, models
from .integrations import (
    IntegrationError,
    JotformClient,
    SupabaseClient,
    search_open_access_works,
)
from .utils import get_service

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET") or os.urandom(32)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

db.init_db()


@app.after_request
def prevent_browser_stale_html(response):
    if request.path == "/" or request.path.endswith(".html") or request.accept_mimetypes.accept_html:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify(error="File is too large. The upload limit is 10 MB."), 413


@app.errorhandler(404)
def page_not_found(error):
    if request.path.startswith("/api/"):
        return jsonify(error="API route not found."), 404
    return render_template("base.html"), 404


@app.context_processor
def shared_template_data():
    return {"current_endpoint": request.endpoint}


@app.get("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="favicon.svg"), code=302)


@app.get("/health")
def health():
    return jsonify(status="ok", application="POLYSTUDY")


@app.route("/")
def index():
    supabase_entries = []
    try:
        supabase_entries = SupabaseClient().list_glossary(limit=6)
    except (IntegrationError, ValueError):
        supabase_entries = []
    return render_template(
        "index.html",
        notes=models.list_notes(),
        quizzes=models.list_study_quizzes(),
        supabase_entries=supabase_entries,
    )


@app.route("/translator")
def translator_page():
    svc = get_service()
    return render_template(
        "translator.html",
        languages=language_list(),
        ai_on=svc.ai_available,
        max_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
    )


@app.route("/notes", methods=["GET", "POST"])
def notes_page():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        language = resolve_language(request.form.get("language")) or "en"
        if not title or not content:
            flash("Add a title and some note content before saving.", "warning")
        else:
            models.create_note(title[:160], content, language)
            flash("Study note saved.", "success")
            return redirect(url_for("notes_page"))
    return render_template("notes.html", notes=models.list_notes(), languages=language_list())


@app.route("/note/<int:nid>")
def note_detail(nid):
    note = models.get_note(nid)
    if not note:
        flash("That study note could not be found.", "warning")
        return redirect(url_for("notes_page"))
    note_data = {"id": note[0], "title": note[1], "content": note[2], "language": note[3]}
    return render_template("note_detail.html", note=note_data, languages=language_list())


@app.route("/quiz")
def quiz_page():
    client = JotformClient()
    return render_template(
        "quiz.html",
        subjects=models.list_quiz_subjects(),
        jotform_form_url=client.form_url,
    )


@app.route("/help")
def help_desk():
    supabase_entries = []
    try:
        supabase_entries = SupabaseClient().list_glossary(limit=100)
    except (IntegrationError, ValueError):
        pass
    return render_template(
        "help.html",
        languages=language_list(),
        ai_on=get_service().ai_available,
        resources=supabase_entries,
        institution="Supabase glossary",
    )


@app.route("/resources")
def resources_page():
    return render_template("resources.html")


@app.get("/api/supabase/glossary")
def api_supabase_glossary():
    language = request.args.get("language", "").strip() or None
    try:
        limit = int(request.args.get("limit", "100"))
    except (TypeError, ValueError):
        return jsonify(error="The glossary limit must be a whole number."), 400
    client = SupabaseClient()
    if not client.configured:
        return jsonify(
            connected=False,
            error=client.configuration_error,
            entries=[],
        ), 200
    try:
        entries = client.list_glossary(language=language, limit=limit)
        return jsonify(connected=True, source="Supabase", entries=entries)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except IntegrationError as exc:
        return jsonify(error=str(exc), connected=False, entries=[]), 502


@app.post("/api/supabase/quiz-result")
def api_supabase_quiz_result():
    payload = request.get_json(silent=True) or {}
    score = payload.get("score")
    client = SupabaseClient()
    if not client.configured:
        return jsonify(error=client.configuration_error), 503
    try:
        saved = client.save_quiz_result(score)
        return jsonify(saved=True, source="Supabase", result=saved)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except IntegrationError as exc:
        return jsonify(error=str(exc)), 502


@app.post("/api/translate")
def api_translate():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    source = resolve_source(payload.get("source"))
    target = resolve_language(payload.get("target"))
    if not text:
        return jsonify(error="Enter some text to translate."), 400
    if len(text) > 20_000:
        return jsonify(error="Text is too long. The limit is 20,000 characters."), 400
    if source is None or target is None:
        return jsonify(error="Choose a supported source and target language."), 400
    try:
        result = get_service().translate_text(text, target, None if source == "auto" else source)
        detected = LANGUAGES.get(result.source)
        target_lang = LANGUAGES[result.target]
        return jsonify(
            translation=result.text,
            source_name=detected.name if detected else "Detected language",
            target_name=target_lang.name,
            target_lang=target_lang.html_lang,
            target_dir="rtl" if target_lang.rtl else "ltr",
            engine=result.engine,
            notes=result.notes,
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except NoEngineError as exc:
        return jsonify(error=str(exc)), 503
    except TranslationError as exc:
        return jsonify(error=str(exc)), 502


@app.post("/api/document")
def api_document():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify(error="Choose a PDF, TXT, or Markdown file first."), 400
    source = resolve_source(request.form.get("source"))
    target = resolve_language(request.form.get("target"))
    if source is None or target is None:
        return jsonify(error="Choose a supported source and target language."), 400
    filename = secure_filename(upload.filename) or "study-notes"
    svc = get_service()
    if not svc.ai_available:
        return jsonify(error="Document translation needs GEMINI_API_KEY or ANTHROPIC_API_KEY in the server environment."), 503
    try:
        result = svc.translate_document(
            upload.read(),
            filename,
            target,
            None if source == "auto" else source,
        )
        return jsonify(
            translation=result.text,
            filename=result.filename,
            source_name=LANGUAGES.get(result.source).name if result.source in LANGUAGES else "Detected language",
            target_name=LANGUAGES[result.target].name,
            chunks=result.chunks,
        )
    except DocumentError as exc:
        return jsonify(error=str(exc)), 400
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except NoEngineError as exc:
        return jsonify(error=str(exc)), 503
    except TranslationError as exc:
        return jsonify(error=str(exc)), 502


@app.get("/api/quizzes")
def api_quizzes():
    language = request.args.get("language", "en")
    if language not in ("en", "sw"):
        return jsonify(error="Bilingual practice is currently available in English and Kiswahili."), 400
    subject = request.args.get("subject", "all")
    subjects = models.list_quiz_subjects()
    if subject != "all" and subject not in subjects:
        return jsonify(error="Choose a subject from the quiz bank."), 400
    quizzes = models.list_study_quizzes(language)
    if subject != "all":
        quizzes = [quiz for quiz in quizzes if quiz["subject"] == subject]
    return jsonify(quizzes=quizzes, subjects=subjects)


@app.post("/api/quizzes/generate")
def api_generate_quiz():
    payload = request.get_json(silent=True) or {}
    language = payload.get("language", "en")
    subject = payload.get("subject", "all")
    count = payload.get("count", 5)
    if language not in ("en", "sw"):
        return jsonify(error="Bilingual practice is currently available in English and Kiswahili."), 400
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 12:
        return jsonify(error="Choose a quiz length between 1 and 12 questions."), 400
    subjects = models.list_quiz_subjects()
    if subject != "all" and subject not in subjects:
        return jsonify(error="Choose a subject from the quiz bank."), 400
    questions = models.list_study_quizzes(language)
    if subject != "all":
        questions = [question for question in questions if question["subject"] == subject]
    if count > len(questions):
        return jsonify(error=f"Only {len(questions)} questions are available for this selection."), 400
    quiz = random.SystemRandom().sample(questions, count)
    return jsonify(
        questions=quiz,
        count=len(quiz),
        subject=subject,
        language=language,
    )


@app.get("/api/jotform/form")
def api_jotform_form():
    client = JotformClient()
    if not client.configured:
        return jsonify(
            connected=False,
            form_url=client.form_url,
            error=client.configuration_error,
        )
    try:
        return jsonify(connected=True, **client.form_summary())
    except IntegrationError as exc:
        return jsonify(error=str(exc)), 502


@app.get("/api/library")
def api_library():
    query = request.args.get("query", "")
    try:
        results = search_open_access_works(query)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except IntegrationError as exc:
        return jsonify(error=str(exc)), 502
    return jsonify(source="OpenAlex", query=" ".join(query.split()), results=results)


@app.get("/api/university-info")
def api_university_info():
    language = request.args.get("language", "en")
    if language not in LANGUAGES:
        return jsonify(error="Choose a supported language."), 400
    try:
        entries = SupabaseClient().list_glossary(limit=100)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except IntegrationError as exc:
        return jsonify(error=str(exc)), 502
    items = [
        {
            "category": row["language"] or "Glossary",
            "title": row["term_en"],
            "body": row["term_translated"],
            "icon": "文",
            "source_url": "",
            "institution": "Supabase",
        }
        for row in entries
    ]
    return jsonify(language=language, translated=False, source="Supabase", items=items)


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)
