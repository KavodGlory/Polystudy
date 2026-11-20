"""Karibu Translator: translate words, sentences and files between nine languages with Claude or Gemini."""
from .chatbot import Chatbot, Reply
from .claude_api import ClaudeClient
from .gemini_api import GeminiClient
from .core import LANGS, Glossary, Match, normalise, resolve_langs
from .errors import DocumentError, NoEngineError, TranslationError
from .languages import LANGUAGES, language_list, resolve_language, resolve_source
from .quiz import make_flashcard, make_question
from .render import format_text
from .service import DocumentResult, TranslationResult, TranslationService
from .unmatched import UnmatchedLog
from .llm import ClaudeFallback

__all__ = [
    "Chatbot", "Reply", "ClaudeClient", "GeminiClient", "LANGS", "Glossary", "Match", "normalise", "resolve_langs",
    "DocumentError", "NoEngineError", "TranslationError", "LANGUAGES", "language_list",
    "resolve_language", "resolve_source", "make_flashcard", "make_question", "format_text",
    "DocumentResult", "TranslationResult", "TranslationService", "UnmatchedLog",
    "ClaudeFallback",
]
