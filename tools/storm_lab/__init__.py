"""Offline developer Storm role/selector evaluator. No game installation is modified."""

VERSION = 1


class Unsupported(ValueError):
    """A selector or operation has no documented emulator implementation."""
