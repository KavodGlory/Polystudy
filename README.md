# Karibu Translator

A chatbot that translates **words, sentences, paragraphs and files (PDF, TXT, MD)** between **nine languages, in any direction**, using the Claude API:

English · Swahili · Sheng (Kenyan street slang) · Arabic · French · Japanese · Spanish · Chinese (Simplified) · German

Type or upload in any of them (or let Claude detect the language) and translate into any of the other eight. Built for international students in Kenya.

## What changed from version 1

| Before | Now |
|---|---|
| Only the ~76 words in the glossary could be translated | Claude translates **any** text. The glossary is no longer the limit |
| Swahili/English/Sheng in, six languages out | **Any of 9 languages in, any other 8 out**, with automatic language detection |
| Words and short phrases only | Sentences, paragraphs and whole **PDF / TXT / MD files** |
| Glossary was the main engine | The glossary is a helper: its verified Kenyan slang is passed to Claude as hints, and its cultural tips show beside translations. Without an API key it still answers single known words |

About the "Google Claude API": Claude is made by Anthropic, and this project calls Anthropic's own Claude API directly. You need an API key from the Anthropic Console (console.anthropic.com). Claude models are also sold through Google Cloud's Vertex AI, which uses different credentials and would need changes to `translator/claude_api.py`.

## Setup

You need Python 3.10 or newer.

```
cd karibu_translator
pip install -r requirements.txt

export ANTHROPIC_API_KEY="your-key"        # Mac / Linux
setx ANTHROPIC_API_KEY "your-key"          # Windows (then open a new terminal)

python3 -m web.app                         # web app: open http://127.0.0.1:5000
python3 cli.py                             # command-line chat
python3 -m pytest                          # tests (no key needed, no network used)
```

**Keep the key secret.** Never paste it into a file you share or commit. API usage is billed by Anthropic per amount of text, so large documents cost more (see "Limits and costs").

### POLYSTUDY student guide

The project also includes a Flask student-study portal built on the Karibu translation service. From the project folder, install the requirements and start it with:

```powershell
$env:GEMINI_API_KEY = "your-new-key"
python -m study_guide.app
```

Then open `http://127.0.0.1:5000`. POLYSTUDY includes translation for study documents, saved notes, generated multi-question quiz sessions, an open-access research catalog, and a student help directory linked to USIU-Africa's public pages. It does not connect to private student records, admissions, billing, or internal university systems.

Quiz sessions are assembled from the local English/Kiswahili study question bank. To inspect the configured Jotform quiz and open it as a hosted form, configure a server-side API key:

```powershell
$env:JOTFORM_API_KEY = "your-rotated-jotform-api-key"
$env:JOTFORM_QUIZ_FORM_ID = "263230744199057"
python -m study_guide.app
```

Jotform's API reads existing form metadata; it is not itself a quiz-generation service. POLYSTUDY uses it to inspect the linked form while generating practice sessions from its question bank. Store the API token only in the server environment, never in source code or browser JavaScript. Revoke and replace any token shared in chat or source files.

The research library searches OpenAlex for works marked open access and caches citation metadata in SQLite for six hours. It links students to publisher or repository pages; availability and licenses still depend on each work. DOAJ and African Journals Online are also linked as external catalogs. Internet access is needed for new searches. English and Kiswahili institutional help links are available offline; other languages need a configured AI service.

Optional settings (environment variables): `KARIBU_MODEL` (default `claude-sonnet-5-5`), `KARIBU_MAX_TOKENS`, `KARIBU_MAX_TEXT_CHARS` (default 20,000), `KARIBU_MAX_DOC_CHARS` (default 150,000).

## Using it

### Web app
Pick **From** (or "Detect language") and **To**, then either:
- **Text tab:** type a word, sentence or several paragraphs and press Translate (Ctrl+Enter also works).
- **File tab:** choose a PDF, TXT or MD file (up to 10 MB). A progress bar shows each piece being translated. Download the result as **.txt** or **.html**. The .html file displays Arabic right-to-left and uses proper Japanese and Chinese fonts, so open it and choose Print, then Save as PDF to get a PDF.

The ⇄ button swaps the two languages. A quiz from the glossary is under "Practice".

### Command line
```
you> Je voudrais une chambre, s'il vous plaît     translated into the current target
you> /to japanese        translate INTO this language (code or name; /to sheng works too)
you> /from german        the language you type (default: auto-detect with /from auto)
you> /file report.pdf    translates the file, saves report.ja.txt and report.ja.html beside it
you> /define asante      glossary card: meaning, translations and tip for a Kenyan word
you> /list sheng   /quiz   /flash   /unmatched   /help   /quit
```

## How it works

```
 text or file
     │
     ▼
 read + split into pieces (≈3,000 characters, at paragraph/sentence boundaries)
     │
     ▼        for each piece
 look up Kenyan slang in the glossary ──► hints
     │
     ▼
 Claude API  (forced structured answer: source language + translation)
     │
     ▼
 join the pieces in order ──► show / download .txt / .html
```

### The Claude client (`translator/claude_api.py`)
- Sends the text with a system prompt that says the text is material to translate and never instructions, so a document that says "ignore your rules" is simply translated.
- Forces Claude to answer through a **tool call** (`submit_translation`) with two fields, `source_language` and `translation`. This is why the program always knows exactly where the translation is and which language was detected, with no fragile text parsing.
- Adds language guidance: Sheng is written as natural casual Nairobi slang (never invented), Swahili as Kenyan Kiswahili, Chinese as Simplified, Arabic as Modern Standard Arabic.
- **Retries** busy or rate-limited responses (HTTP 429, 5xx, 529) and network errors with waits of 2, 4 and 8 seconds, then gives a clear message. Bad keys, unknown models and other errors are explained in plain words, and the key never appears in messages.

### Long text and files (`translator/documents.py`, `translator/service.py`)
- **Chunking:** text is cut at paragraph boundaries (long paragraphs at sentence ends). The pieces are translated in order and rejoined with the original paragraph breaks. The language detected on the first piece is reused for the rest, so the whole document is treated consistently.
- **If an answer is cut off** because a piece was too long, that piece is automatically split in half and retried.
- **PDFs:** text is extracted with `pypdf` (falling back to the `pdftotext` tool), and the hard line breaks a PDF puts mid-sentence are repaired, including for Chinese and Japanese.
- **Scanned PDFs** (images with no text) are sent to Claude directly, which can read them visually. This is limited to about 100 pages and to as much text as fits in one answer.
- **Web jobs (`web/jobs.py`):** a file translation runs in a background thread, the page polls for progress, and at most 3 run at once. Jobs are kept in memory for an hour.

### The glossary (`data/glossary.json`)
76 entries of everyday Kenyan phrases and slang, each with a meaning, a cultural tip, all six translations and a `needs_review` flag. It now does three smaller jobs:
1. **Hints:** if your text contains Sheng or Kenyan English terms (such as *mambo*, *msee*, *matatu*), the verified meanings are given to Claude with the instruction to use them only if the term is clearly used that way.
2. **Tips:** short cultural notes are shown beside a translation of a short input.
3. **Offline mode:** with no API key, a single known word or phrase can still be translated, and `/define`, `/quiz` and `/flash` work.

The matching engine (`translator/core.py`: normalise, exact, phrase, fuzzy, reverse) is unchanged from version 1.

## Limits and costs
- Text box: 20,000 characters. Files: 10 MB and 150,000 characters of text (about 60 to 100 pages). Change the limits with the environment variables above.
- Each piece costs API tokens, and Arabic, Japanese and Chinese use more tokens per word. Try a short file first to see what it costs you.
- A 100,000-character document is about 35 requests and may take several minutes.

## Honest limitations
- **I could not test against the live Claude API** (this build environment has no key or internet). All 230 tests use a simulated API, and the web page was driven in a real browser against it. The request format follows the Messages API with forced tool use, but run one real translation first and check the result. If your key cannot use the default model, set `KARIBU_MODEL`.
- **AI translation can be wrong.** For legal, medical, immigration or academic documents, have a qualified translator check it.
- **Sheng is the weakest area.** It is informal, varies by area and age, and is thinly covered in training data. Sheng output is always marked for review by a Kenyan speaker.
- **PDF layout is not preserved.** Output is clean text in reading order, not a copy of the original design. Tables, columns, images and footnotes may come out in an odd order, and text inside images is skipped (unless the whole PDF is a scan).
- **Not supported yet:** Word (.docx), password-protected PDFs, and getting a PDF back directly (use the .html and print to PDF).
- The glossary translations I drafted are still not checked by native speakers (15 are flagged).
- The web server is for local use. Before exposing it to the internet, run it behind a production server (such as gunicorn), add logins and rate limiting, and remember that anyone who can use it spends your API credit.

## Folder structure

```
karibu_translator/
├── data/glossary.json         verified Kenyan phrases and slang (hints, tips, offline mode)
├── translator/
│   ├── languages.py           the 9 languages, aliases, right-to-left flags
│   ├── claude_api.py          Claude API client: structured output, retries, PDF support
│   ├── service.py             translate_text / translate_document, chunking, hints, offline fallback
│   ├── documents.py           PDF/TXT reading, reflow, chunking, .txt/.html writers
│   ├── core.py                glossary indexes and matching engine
│   ├── chatbot.py, render.py  glossary definitions ("/define")
│   ├── quiz.py, unmatched.py  quiz/flashcards and the unmatched-lookup log
│   └── errors.py
├── cli.py                     command-line chat
├── web/                       Flask app, background jobs, page (RTL aware)
├── tests/                     230 tests
├── requirements.txt
└── pytest.ini
```

## Roadmap
1. Run a real test with your key, then have native speakers review the glossary, starting with the flagged and Sheng entries.
2. Word (.docx) input and output, so students get a translated document in the same format.
3. Keep the original layout of PDFs (render the translation into a PDF with proper Arabic and CJK fonts).
4. Save translations as a shared glossary: log each Sheng translation a Kenyan reviewer approves.
5. WhatsApp or Telegram front end that reuses `TranslationService`.
6. Text-to-speech for pronunciation.
#   P o l y s t u d y  
 #   P o l y s t u d y  
 