"""Errors shared by the data layer (kept dependency-free so any module can import them)."""


class SourceError(Exception):
    """A source could not be fetched or parsed. Messages never contain secrets."""
