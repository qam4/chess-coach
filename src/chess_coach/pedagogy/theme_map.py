"""Map the engine's per-line theme label to knowledge-bank features.

The engine tags each candidate line with a short theme
(``label_line_theme`` in Blunder: ``piece development``,
``king safety, castling``, ``central pawn break``, ``material win``,
``king attack``, ``general play``). When the coach leads with a sound
move, we bias the pedagogy selection toward guidance about *that move's
theme*, so the "what to focus on" half of the teaching bridge matches the
concrete move being recommended.

This is a soft **bias**, never a restriction (grounded-move-advice
Req 4.2): the features here are added as a ranking preference on top of
the position's own feature match. An unmapped theme (or ``general play``)
contributes nothing and the selection is exactly as it would be without a
preferred theme (Req 4.2, 4.3). The bank is never a source of a concrete
move (Req 4.3) — only of the theme and how-to-think.

The feature names below are drawn from the closed vocabulary in
``data/pedagogy/knowledge.yaml`` / ``schema.md``.
"""

from __future__ import annotations

# Engine theme -> preferred knowledge-bank feature(s). Only themes with a
# sensible pedagogy analogue are mapped; "general play" (and anything the
# engine adds later that is unmapped) yields no bias.
_THEME_TO_FEATURES: dict[str, frozenset[str]] = {
    "piece development": frozenset({"phase:opening"}),
    "central pawn break": frozenset({"phase:opening"}),
    "king safety, castling": frozenset({"exposed_king"}),
    "king attack": frozenset({"exposed_king"}),
    "material win": frozenset({"hanging_piece_opponent"}),
}


def theme_features(theme: str) -> frozenset[str]:
    """Preferred knowledge-bank features for an engine theme label.

    Returns an empty set for an unknown/unmapped theme (including
    ``"general play"``), which leaves the guidance selection unbiased.
    """
    return _THEME_TO_FEATURES.get(theme.strip().lower(), frozenset())
