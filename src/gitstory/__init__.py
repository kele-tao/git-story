"""git-story: read any git history as an engineering narrative."""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__", "GitError", "History", "scan"]

from .gitio import GitError
from .history import History, scan
