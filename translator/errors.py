"""Exceptions the interfaces turn into friendly messages."""


class TranslationError(Exception):
    """The translation could not be produced (API problem, bad response ...)."""


class TruncatedError(TranslationError):
    """Claude's answer was cut off because the piece of text was too long."""


class NoEngineError(TranslationError):
    """No API key is configured and the glossary cannot answer."""


class DocumentError(ValueError):
    """The uploaded file cannot be used (wrong type, empty, too large, unreadable)."""
