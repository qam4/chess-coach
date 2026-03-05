"""Smoke tests — verify the package is importable and version is set."""

import chess_coach


def test_import_chess_coach():
    """Package should be importable."""
    assert chess_coach is not None


def test_version_string():
    """Package should expose a version string."""
    assert hasattr(chess_coach, "__version__")
    assert isinstance(chess_coach.__version__, str)
    assert chess_coach.__version__ == "0.1.0"
