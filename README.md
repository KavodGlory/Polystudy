# Karibu Translator and POLYSTUDY

Karibu is a Python project with two local web applications and a command-line
translator:

- **Karibu Translator** translates text between English, Kiswahili, Sheng,
  Arabic, French, Japanese, Spanish, Simplified Chinese, and German. It can
  also translate PDF, TXT, and Markdown documents. A Kenyan-language glossary
  supports definitions, cultural notes, practice quizzes, and limited
  translations when no AI service is configured.
- **POLYSTUDY** is a student study portal with saved notes, practice quizzes,
  public student-help links, and a search of open-access research metadata.
  It reuses Karibu's translation service.

The applications are intended for local use and each starts on
`http://127.0.0.1:5000`. Run one at a time unless you configure different
ports.

## Requirements

- Python 3.10 or newer
- Internet access and an API key for AI translations (optional)

The glossary-only translator features and tests can be used without an API key.
AI-powered text and document translation requires a key from either
[Google AI Studio](https://aistudio.google.com/) or the
[Anthropic Console](https://console.anthropic.com/). If both keys are set,
Google Gemini is selected first.

## Set up

Run these commands from the project directory.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### macOS or Linux

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

To enable AI translation, set one provider key in the terminal before starting
an application. For example:

```powershell
$env:GEMINI_API_KEY = "your-key"
```

```sh
export GEMINI_API_KEY="your-key"
```

Alternatively, set `ANTHROPIC_API_KEY`. Keep API keys out of source files,
screenshots, and commits; use a secret manager or your operating system's
environment settings for persistent configuration.

## Run an application

Start **one** of these from the project directory:

```sh
python -m web.app
```

Then visit `http://127.0.0.1:5000` for the translator web app.

```sh
python -m study_guide.app
```

Then visit the same address for POLYSTUDY.

For the command-line translator, run:

```sh
python cli.py
```

Type `/help` in the CLI for available commands. Without an AI key, it can
still look up glossary entries and run its glossary-based practice features.

## Optional POLYSTUDY integration

POLYSTUDY can inspect an existing Jotform quiz form. This integration is
optional; the portal's local practice-question bank does not require Jotform.
Configure these server environment variables to enable the Jotform connection:

```powershell
$env:JOTFORM_API_KEY = "your-key"
$env:JOTFORM_QUIZ_FORM_ID = "your-form-id"
```

The form ID defaults to the project-configured form if omitted. The app uses
Jotform to read form metadata; it does not create quiz content there. Never
put the API key in application code or browser JavaScript.

The research search uses OpenAlex and needs an internet connection for new
searches. Search metadata is cached locally.

## Run tests

Install the requirements, then run:

```sh
python -m pytest
```

The tests use local fixtures and mocks; they do not require live AI or Jotform
credentials.

## Configuration

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Enable Google Gemini. Takes priority when both AI keys are set. |
| `ANTHROPIC_API_KEY` | Enable Anthropic Claude if Gemini is not configured. |
| `KARIBU_MODEL` | Override the selected provider's default model. |
| `KARIBU_MAX_TOKENS` | Override Claude's maximum response tokens. |
| `KARIBU_MAX_TEXT_CHARS` | Maximum text input size (default: 20,000 characters). |
| `KARIBU_MAX_DOC_CHARS` | Maximum extracted document text (default: 150,000 characters). |
| `JOTFORM_API_KEY` | Optional server-side key for reading Jotform form details. |
| `JOTFORM_QUIZ_FORM_ID` | Optional Jotform form ID. |
| `FLASK_SECRET` | Optional persistent Flask session secret for POLYSTUDY. |

AI provider usage may incur charges or be subject to provider quotas. Review
each provider's current terms and pricing before sending text or documents.

## Project layout

```text
data/
  glossary.json          Kenyan phrases, translations, and cultural notes
translator/              Translation, glossary, and document-processing logic
web/                     Karibu Translator Flask application
study_guide/             POLYSTUDY Flask application and SQLite data layer
cli.py                   Command-line translator
tests/                   Automated tests
requirements.txt         Python dependencies
```

POLYSTUDY creates `study_guide/study_guide.db` on first run. It is local
application data and may contain saved notes, so it is intentionally excluded
from Git. The `data/glossary.json` file is project content and should be
committed; `data/unmatched.jsonl` is a generated lookup log and should not.

## Notes and limitations

- AI translations can be inaccurate. Have a qualified translator review
  important legal, medical, immigration, or academic material. Sheng varies by
  community and should be checked by a Kenyan speaker.
- PDF text extraction may not preserve the original layout, and scanned PDFs
  have additional processing limits.
- These Flask apps are configured for local development, not direct exposure
  to the public internet. A public deployment needs appropriate production
  hosting, authentication, rate limiting, and protection of API credentials.
