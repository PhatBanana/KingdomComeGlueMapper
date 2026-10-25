"""Offline developer quest/NPC interpreter. No game installation is modified."""

VERSION = 1


class Unsupported(ValueError):
    """An operation has no documented emulator implementation."""


class BudgetExceeded(RuntimeError):
    """The scenario exceeded its bounded execution budget."""
