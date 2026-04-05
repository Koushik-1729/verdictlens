"""
Backward-compatible re-export of the v2 blame engine.

All logic lives in :mod:`app.blame_engine`.
"""

from app.blame_engine import compute_blame  # noqa: F401
