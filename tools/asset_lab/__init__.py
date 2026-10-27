"""Offline developer render/stream asset contract gate. No game files are modified."""

VERSION = 1

PASS, FAIL, REVIEW, UNSUPPORTED, ERROR = 'PASS', 'FAIL', 'REVIEW', 'UNSUPPORTED', 'ERROR'
NON_PASSING = (FAIL, ERROR, UNSUPPORTED)


class Unsupported(ValueError):
    """A required input or rule has no documented implementation."""


def norm(name):
    return name.replace('\\', '/').lstrip('/').lower()
