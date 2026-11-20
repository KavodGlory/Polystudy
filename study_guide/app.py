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
    search_open_access_works,
)
from .utils import get_service

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET") or os.urandom(32)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

db.init_db()


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify(error="File is too large. The upload limit is 10 MB."), 413


@app.context_processor
def shared_template_data():
    return {"current_endpoint": request.endpoint}


@app.route("/")
def index():
    return render_template(
        "index.html",
        notes=models.list_notes(),
        quizzes=models.list_study_quizzes(),
        resources=models.list_institution_resources(),
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
    return render_template(
        "help.html",
        languages=language_list(),
        ai_on=get_service().ai_available,
        resources=models.list_institution_resources(),
        institution="USIU-Africa",
    )


@app.route("/resources")
def resources_page():
    return render_template("resources.html")


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
    entries = models.list_institution_resources()
    if language == "en":
        return jsonify(language=language, translated=False, items=[
            {"category": row["category"], "title": row["title"], "body": row["summary"],
             "icon": row["icon"], "source_url": row["url"], "institution": row["institution"]}
            for row in entries
        ])
    if language == "sw":
        return jsonify(language=language, translated=False, items=[
            {"category": row["category"], "title": row["title_sw"], "body": row["summary_sw"],
             "icon": row["icon"], "source_url": row["url"], "institution": row["institution"]}
            for row in entries
        ])

    svc = get_service()
    if not svc.ai_available:
        return jsonify(error="This language needs AI translation. Set GEMINI_API_KEY or ANTHROPIC_API_KEY in the server environment, or choose English."), 503
    translated_items = []
    try:
        for row in entries:
            title = svc.translate_text(row["title"], language, "en").text
            body = svc.translate_text(row["summary"], language, "en").text
            translated_items.append({
                "category": row["category"],
                "title": title,
                "body": body,
                "icon": row["icon"],
                "source_url": row["url"],
                "institution": row["institution"],
            })
    except (ValueError, NoEngineError, TranslationError) as exc:
        return jsonify(error=str(exc)), 502
    return jsonify(language=language, translated=True, items=translated_items)


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
