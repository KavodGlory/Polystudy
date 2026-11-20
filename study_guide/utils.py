"""Utility helpers – pick AI client and expose TranslationService as singleton."""
import os
from translator import TranslationService, Glossary, GeminiClient, ClaudeClient

def pick_client():
    """Return the first available AI client (Gemini > Claude) or None."""
    if os.getenv("GEMINI_API_KEY"):
        return GeminiClient()
    if os.getenv("ANTHROPIC_API_KEY"):
        return ClaudeClient()
    return None

def get_service():
    """Singleton TranslationService used by Flask routes."""
    if not hasattr(get_service, "_svc"):
        client = pick_client()
        get_service._svc = TranslationService(Glossary.load(), client)
    return get_service._svc

