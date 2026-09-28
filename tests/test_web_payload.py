"""The play payload and the UI that reads it, checked against each other.

There are no web tests in this repo, so this is the first. It exists for one failure mode
that nothing else can catch: `server.py` emits a key and `app.js` reads a different one, and
the hint silently never appears. No server is started and no engine is needed — the check is
on the contract, which is the part that drifts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SERVER = _ROOT / "src" / "chess_coach" / "web" / "server.py"
_APP_JS = _ROOT / "src" / "chess_coach" / "web" / "static" / "app.js"


@pytest.mark.parametrize(
    "key",
    [
        "hint_san",  # prospective: what to play NEXT
        "better_move_san",  # retrospective: the alternative to the move just played (B-012)
    ],
)
def test_every_hint_key_the_server_emits_is_read_by_the_ui(key: str) -> None:
    server = _SERVER.read_text(encoding="utf-8")
    app_js = _APP_JS.read_text(encoding="utf-8")
    assert f'"{key}"' in server, f"{key} is not in the play payload"
    assert f"data.{key}" in app_js, f"the server emits {key} and the UI never reads it"


def test_the_two_hints_are_labelled_differently_in_the_ui() -> None:
    """They are different moves and must not read as one.

    `hint_san` is the best move in the position the student now faces. `better_move_san` is
    the move that would have been better than the one they just played. Presenting either
    under the other's wording tells the student to play a move that is no longer on the
    board, or credits an alternative as current advice.
    """
    app_js = _APP_JS.read_text(encoding="utf-8")
    assert "Better than your move was: " in app_js
    assert "Consider playing: " in app_js
