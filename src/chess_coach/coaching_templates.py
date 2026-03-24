"""Template-based coaching text generator.

Produces factual coaching text directly from structured engine data.
No LLM needed — instant, deterministic, never hallucinates.

This is Layer 1 of the hybrid coaching approach. The output can be
used standalone or passed to an LLM for tone/personality rephrasing.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from chess_coach.models import ComparisonReport, PositionReport
from chess_coach.openings import OpeningInfo


@dataclass
class CoachingArrow:
    """An arrow to draw on the board."""

    from_sq: str  # e.g. "c4"
    to_sq: str  # e.g. "f7"
    color: str = "#e74c3c"  # red by default


@dataclass
class CoachingSection:
    """A single section of coaching output."""

    category: str  # assessment, piece_safety, tactics, strategy, tensions, suggestion
    label: str  # human-readable label for UI rendering
    text: str  # the coaching text
    arrows: list[CoachingArrow] | None = None  # optional board arrows

    def to_dict(self) -> dict:
        """Serialize for JSON API responses."""
        d: dict = {
            "category": self.category,
            "label": self.label,
            "text": self.text,
        }
        if self.arrows:
            d["arrows"] = [
                {"from": a.from_sq, "to": a.to_sq, "color": a.color}
                for a in self.arrows
            ]
        return d


# Category constants
CAT_ASSESSMENT = "assessment"
CAT_PIECE_SAFETY = "piece_safety"
CAT_TACTICS = "tactics"
CAT_STRATEGY = "strategy"
CAT_TENSIONS = "tensions"
CAT_SUGGESTION = "suggestion"

_CATEGORY_LABELS = {
    CAT_ASSESSMENT: "Assessment",
    CAT_PIECE_SAFETY: "Piece safety",
    CAT_TACTICS: "Tactics",
    CAT_STRATEGY: "Strategy",
    CAT_TENSIONS: "Tensions",
    CAT_SUGGESTION: "Suggestion",
}


def generate_position_coaching_structured(
    report: PositionReport,
    level: str = "intermediate",
    opening: OpeningInfo | None = None,
) -> list[CoachingSection]:
    """Generate structured coaching sections from a PositionReport.

    Returns a list of CoachingSection objects, each with a category,
    label, and text. The UI can render these as tabs, collapsible
    sections, or a flat list.
    """
    sections: list[CoachingSection] = []

    # Assessment
    sections.append(
        CoachingSection(
            CAT_ASSESSMENT,
            _CATEGORY_LABELS[CAT_ASSESSMENT],
            _eval_summary(report),
        )
    )

    # Piece safety — hanging pieces
    hanging = _hanging_pieces_text(report)
    if hanging:
        # Highlight hanging piece squares
        hanging_arrows = []
        for side in ("white", "black"):
            for hp in report.hanging_pieces.get(side, []):
                hanging_arrows.append(
                    CoachingArrow(hp.square, hp.square, "#e74c3c")
                )
        sections.append(
            CoachingSection(
                CAT_PIECE_SAFETY,
                _CATEGORY_LABELS[CAT_PIECE_SAFETY],
                hanging,
                arrows=hanging_arrows or None,
            )
        )

    # Tactics — threats, checks, captures, motifs
    threats_and_tactics = _threats_and_tactics_text(report)
    if threats_and_tactics:
        tactic_arrows = _extract_arrows(report)
        sections.append(
            CoachingSection(
                CAT_TACTICS,
                _CATEGORY_LABELS[CAT_TACTICS],
                threats_and_tactics,
                arrows=tactic_arrows or None,
            )
        )

    # Strategy — king safety + pawn structure
    strategy_parts: list[str] = []
    king = _king_safety_text(report, level)
    if king:
        strategy_parts.append(king)
    pawns = _pawn_structure_text(report, level)
    if pawns:
        strategy_parts.append(pawns)
    if strategy_parts:
        sections.append(
            CoachingSection(
                CAT_STRATEGY,
                _CATEGORY_LABELS[CAT_STRATEGY],
                " ".join(strategy_parts),
            )
        )

    # Tensions — contested squares, under-defended pieces
    tensions = _board_tensions_text(report)
    if tensions:
        sections.append(
            CoachingSection(
                CAT_TENSIONS,
                _CATEGORY_LABELS[CAT_TENSIONS],
                tensions,
            )
        )

    # Suggestion — what to think about
    best = _best_move_text(report)
    if best:
        sections.append(
            CoachingSection(
                CAT_SUGGESTION,
                _CATEGORY_LABELS[CAT_SUGGESTION],
                best,
            )
        )

    return sections


def _extract_arrows(report: PositionReport) -> list[CoachingArrow]:
    """Extract board arrows from threats and tactics."""
    arrows: list[CoachingArrow] = []

    # Tactics: source → targets
    for t in report.tactics:
        if t.squares and len(t.squares) >= 2:
            src = t.squares[0]
            for tgt in t.squares[1:]:
                arrows.append(CoachingArrow(src, tgt, "#f59e0b"))

    # Threats: source → target squares
    for side in ("white", "black"):
        color = "#3b82f6" if side == "white" else "#e74c3c"
        for threat in report.threats.get(side, []):
            for tgt in threat.target_squares:
                arrows.append(
                    CoachingArrow(threat.source_square, tgt, color)
                )

    return arrows


def generate_position_coaching(
    report: PositionReport,
    level: str = "intermediate",
    opening: OpeningInfo | None = None,
) -> str:
    """Generate coaching text from a PositionReport without an LLM.

    Returns a multi-paragraph coaching explanation built entirely from
    the structured engine data. For structured output (categories),
    use generate_position_coaching_structured() instead.
    """
    sections = generate_position_coaching_structured(
        report, level=level, opening=opening
    )
    return "\n\n".join(s.text for s in sections)


def _move_number_from_fen(fen: str) -> int:
    """Extract the full-move number from a FEN string.

    The move number is the last field in a FEN. Returns 1 if parsing fails.
    """
    try:
        return int(fen.split()[-1])
    except (IndexError, ValueError):
        return 1


def effective_move_classification(report: ComparisonReport) -> str:
    """Return the coaching-adjusted classification for a move.

    In the opening (first 6 moves), engine eval at shallow depth is
    unreliable — only flag moves with a large eval drop (>150cp).
    This prevents sound openings like 1...e5, 1.d4, or the Scandinavian
    from being called inaccuracies or mistakes.
    """
    cls = report.classification
    if cls != "good" and _move_number_from_fen(report.fen) <= 6:
        if report.eval_drop_cp <= 150:
            return "good"
    return cls


def generate_move_coaching(
    report: ComparisonReport,
    level: str = "intermediate",
) -> str:
    """Generate move evaluation coaching from a ComparisonReport."""
    sections: list[str] = []

    # Override engine classification for early opening moves.
    # At shallow depth, the engine's eval is unreliable for opening moves —
    # it may penalize perfectly sound openings (e.g. 1...e5, 1.d4, Scandinavian).
    # In the first few moves, only flag moves with a large eval drop.
    cls = effective_move_classification(report)
    drop = abs(report.eval_drop_cp)

    if cls == "good":
        sections.append("Good move!")
    else:
        before = report.best_eval_cp / 100
        after = report.user_eval_cp / 100
        eval_shift = f" (eval {before:+.1f} → {after:+.1f})"
        if cls == "inaccuracy":
            sections.append(
                f"That's a small inaccuracy — you lost about "
                f"{drop / 100:.1f} pawns of advantage{eval_shift}."
            )
        elif cls == "mistake":
            sections.append(
                f"That's a mistake — it costs about "
                f"{drop / 100:.1f} pawns{eval_shift}."
            )
        elif cls == "blunder":
            sections.append(
                f"That's a blunder — it drops "
                f"{drop / 100:.1f} pawns{eval_shift}. "
                f"Let's look at what went wrong."
            )

    # What was stronger
    if report.best_move and cls != "good":
        try:
            board = chess.Board(report.fen)
            move = chess.Move.from_uci(report.best_move)
            best_san = board.san(move)
        except (ValueError, chess.InvalidMoveError):
            best_san = report.best_move
        sections.append(f"{best_san} was stronger here.")

    # Missed tactics
    if report.missed_tactics:
        for tactic in report.missed_tactics:
            sections.append(
                f"You missed a {tactic.type.replace('_', ' ')}: "
                f"{tactic.description}"
            )

    # Refutation line
    if report.refutation_line and cls in ("mistake", "blunder"):
        try:
            board = chess.Board(report.fen)
            # Push user move first, then convert refutation to SAN
            board.push(chess.Move.from_uci(report.user_move))
            san_moves = []
            for uci_move in report.refutation_line:
                m = chess.Move.from_uci(uci_move)
                san_moves.append(board.san(m))
                board.push(m)
            sections.append(f"The opponent can punish this with: {' '.join(san_moves)}")
        except (ValueError, chess.InvalidMoveError):
            moves = " ".join(report.refutation_line)
            sections.append(f"The opponent can punish this with: {moves}")

    return "\n\n".join(sections)


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------


def _eval_summary(report: PositionReport) -> str:
    """Summarize the overall evaluation in plain language."""
    cp = report.eval_cp
    abs_cp = abs(cp)

    if abs_cp < 30:
        assessment = "The position is roughly equal."
    elif abs_cp < 100:
        side = "White" if cp > 0 else "Black"
        assessment = f"{side} has a slight edge ({cp / 100:+.2f} pawns)."
    elif abs_cp < 300:
        side = "White" if cp > 0 else "Black"
        assessment = f"{side} has a clear advantage ({cp / 100:+.2f} pawns)."
    else:
        side = "White" if cp > 0 else "Black"
        assessment = f"{side} is winning ({cp / 100:+.2f} pawns)."

    # Add context from the eval breakdown factors.
    # If the dominant factor aligns with the overall eval, present it as
    # "the main factor."  If it contradicts (e.g. White is ahead but Black
    # has better king safety), present both sides — that's actually more
    # insightful coaching.
    eb = report.eval_breakdown
    factors = [
        (abs(eb.mobility), eb.mobility, "piece activity"),
        (abs(eb.king_safety), eb.king_safety, "king safety"),
        (abs(eb.pawn_structure), eb.pawn_structure, "pawn structure"),
    ]
    factors.sort(reverse=True)
    if abs_cp > 30:
        top_abs, top_val, top_name = factors[0]
        if top_abs > 30:
            top_better = "White" if top_val > 0 else "Black"
            eval_side = "White" if cp > 0 else "Black"
            if top_better == eval_side:
                assessment += (
                    f" The main factor is {top_name}"
                    f" ({top_better} is better)."
                )
            else:
                # Dominant factor favours the other side — find what
                # actually drives the advantage and present both.
                for _, val, name in factors[1:]:
                    aligned = "White" if val > 0 else "Black"
                    if abs(val) > 20 and aligned == eval_side:
                        assessment += (
                            f" {eval_side}'s {name} outweighs"
                            f" {top_better}'s {top_name} edge."
                        )
                        break

    return assessment


def _hanging_pieces_text(report: PositionReport) -> str | None:
    """Describe hanging pieces."""
    pieces = []
    for hp in report.hanging_pieces.get("white", []):
        pieces.append(f"White's {hp.piece} on {hp.square} is undefended")
    for hp in report.hanging_pieces.get("black", []):
        pieces.append(f"Black's {hp.piece} on {hp.square} is undefended")

    if not pieces:
        return None
    return "Piece safety: " + ". ".join(pieces) + "."


def _threats_text(report: PositionReport) -> str | None:
    """Describe active threats using board state and structured data."""
    items = []
    try:
        board = chess.Board(report.fen)
    except ValueError:
        return None

    for side_key, side_name in [("white", "White"), ("black", "Black")]:
        for t in report.threats.get(side_key, []):
            piece_name = _piece_name_at(board, t.source_square)
            source = f"{side_name}'s {piece_name} on {t.source_square}" if piece_name else side_name

            # Build description from structured fields when possible
            if t.type == "check" and t.target_squares:
                via = ", ".join(t.target_squares)
                items.append(f"{source} can give check on {via}.")
            elif t.type == "capture" and t.target_squares:
                targets = ", ".join(t.target_squares)
                items.append(f"{source} threatens to capture on {targets}.")
            elif t.description:
                # Fallback to engine description for types we don't handle yet
                items.append(f"{source}: {t.description}")
            else:
                items.append(
                    f"{source} has a threat"
                    f" ({t.type.replace('_', ' ')})."
                )

    if not items:
        return None
    return "Threats: " + " ".join(items)


def _threats_and_tactics_text(report: PositionReport) -> str | None:
    """Merge threats and tactics into one section, deduplicating."""
    items: list[str] = []
    seen_types: set[str] = set()

    try:
        board = chess.Board(report.fen)
    except ValueError:
        board = None

    # Tactics first (more specific)
    seen_descriptions: set[str] = set()
    for t in report.tactics:
        key = t.type.lower()
        seen_types.add(key)
        # If this tactic involves a check, also suppress the "check" threat
        desc_lower = t.description.lower() if t.description else ""
        if "check" in desc_lower:
            seen_types.add("check")
        # Human-friendly tactic label: replace underscores, title-case
        label = t.type.replace("_", " ").capitalize()
        piece_name = ""
        if board and t.squares:
            piece_name = _piece_name_at(board, t.squares[0]) or ""
        if piece_name and len(t.squares) >= 2:
            text = (
                f"{label}: {piece_name} on "
                f"{t.squares[0]} targets {', '.join(t.squares[1:])}"
            )
        elif t.in_pv:
            # Tactic is in the principal variation, not on the board yet.
            # Skip it — the threat will be shown when it's on the board.
            continue
        else:
            text = f"{label}: {t.description}"
        # Skip duplicate text
        if text not in seen_descriptions:
            seen_descriptions.add(text)
            items.append(text)

    # Add threats that aren't already covered by tactics
    for side_key, side_name in [("white", "White"), ("black", "Black")]:
        for threat in report.threats.get(side_key, []):
            if threat.type.lower() in seen_types:
                continue
            piece_name = ""
            if board:
                piece_name = _piece_name_at(board, threat.source_square) or ""
            source = (
                f"{side_name}'s {piece_name} on {threat.source_square}" if piece_name else side_name
            )
            if threat.type == "check" and threat.target_squares:
                via = ", ".join(threat.target_squares)
                items.append(f"{source} can give check on {via}.")
            elif threat.type == "capture" and threat.target_squares:
                targets = ", ".join(threat.target_squares)
                items.append(f"{source} threatens to capture on {targets}.")
            elif threat.description:
                items.append(f"{source}: {threat.description}")

    if not items:
        return None
    return " ".join(items)


def _piece_name_at(board: chess.Board, square_name: str) -> str | None:
    """Get the piece name at a square, or None."""
    try:
        sq = chess.parse_square(square_name)
        piece = board.piece_at(sq)
        if piece is None:
            return None
        names = {
            chess.PAWN: "pawn",
            chess.KNIGHT: "knight",
            chess.BISHOP: "bishop",
            chess.ROOK: "rook",
            chess.QUEEN: "queen",
            chess.KING: "king",
        }
        return names.get(piece.piece_type)
    except ValueError:
        return None


def _king_safety_text(report: PositionReport, level: str) -> str | None:
    """Describe king safety concerns using board state, not engine descriptions.

    Suppresses warnings in the early opening (first ~8 moves) when not
    castling is normal. Also suppresses castling advice in endgames where
    it's irrelevant.
    """
    try:
        board = chess.Board(report.fen)
    except ValueError:
        return None

    # Suppress king safety advice in endgames (few pieces left).
    # Castling and king exposure are irrelevant when there's no attack.
    total_pieces = len(board.piece_map())
    if total_pieces <= 6:
        return None

    move_number = board.fullmove_number
    parts = []

    for color, side_name in [(chess.WHITE, "White"), (chess.BLACK, "Black")]:
        ks = report.king_safety.get(side_name.lower())
        if not ks or ks.score >= -10:
            continue

        king_sq = board.king(color)
        if king_sq is None:
            continue

        has_castling = board.has_castling_rights(color)
        king_rank = chess.square_rank(king_sq)
        home_rank = 0 if color == chess.WHITE else 7
        is_on_home_rank = king_rank == home_rank

        # Very early opening (moves 1-3): don't nag about not castling yet.
        # By move 4+, castling advice becomes relevant — the engine's top
        # lines often include O-O by this point.
        if move_number <= 3 and is_on_home_rank and has_castling:
            continue

        # Build a context-aware description
        if not is_on_home_rank:
            parts.append(
                f"{side_name}'s king has been displaced to "
                f"{chess.square_name(king_sq)} — be careful."
            )
        elif has_castling:
            parts.append(f"{side_name}'s king is still in the center. Consider castling soon.")
        elif not has_castling and is_on_home_rank:
            # Lost castling rights but king is still on home rank
            parts.append(f"{side_name}'s king can no longer castle — keep it protected.")
        elif ks.score < -30:
            # Significant danger — use a stronger warning
            parts.append(f"{side_name}'s king is exposed and vulnerable.")

    if not parts:
        return None
    return " ".join(parts)


def _pawn_structure_text(report: PositionReport, level: str) -> str | None:
    """Describe notable pawn structure features."""
    if level == "beginner":
        return None  # Too advanced for beginners

    parts = []
    for side_name, side_key in [("White", "white"), ("Black", "black")]:
        features = report.pawn_structure.get(side_key)
        if not features:
            continue
        if features.isolated:
            files = ", ".join(features.isolated)
            parts.append(f"{side_name} has isolated pawns on the {files}-file(s)")
        if features.doubled:
            files = ", ".join(features.doubled)
            parts.append(f"{side_name} has doubled pawns on the {files}-file")
        if features.passed:
            files = ", ".join(features.passed)
            parts.append(f"{side_name} has a passed pawn on the {files}-file")

    if not parts:
        return None
    return "Pawn structure: " + ". ".join(parts) + "."


def _tactics_text(report: PositionReport) -> str | None:
    """Describe detected tactical motifs."""
    if not report.tactics:
        return None
    items = []
    for t in report.tactics:
        label = t.type.replace("_", " ").capitalize()
        items.append(f"{label}: {t.description}")
    return "Tactics: " + ". ".join(items) + "."


def _best_move_text(report: PositionReport) -> str | None:
    """Position-aware advice without revealing the specific best move.

    The hint button is for concrete move suggestions. The coaching text
    should focus on what to think about, not what to play.
    """
    if not report.top_lines or not report.top_lines[0].moves:
        return None

    try:
        board = chess.Board(report.fen)
        move = chess.Move.from_uci(report.top_lines[0].moves[0])
        piece = board.piece_at(move.from_square)

        # Give positional guidance based on what the best move does
        if board.san(move) in ("O-O", "O-O-O"):
            return "Consider castling to get your king to safety."

        # King moves in endgames — king activity is key
        total_pieces = len(board.piece_map())
        if piece and piece.piece_type == chess.KING and total_pieces <= 10:
            return "Activate your king — in the endgame, the king is a strong piece."

        if piece and piece.piece_type in (chess.KNIGHT, chess.BISHOP):
            back_rank = 0 if board.turn == chess.WHITE else 7
            if chess.square_rank(move.from_square) == back_rank:
                return "Develop your pieces and fight for the center."

        # Pawn moves toward the center in the opening
        if piece and piece.piece_type == chess.PAWN:
            target_file = chess.square_file(move.to_square)
            if target_file in (2, 3, 4, 5) and board.fullmove_number <= 6:
                return "Control the center with your pawns and develop your pieces."

        if board.is_capture(move):
            return "There's a tactical opportunity — look for captures."

        # Check if there are hanging pieces to address
        side = "white" if board.turn == chess.WHITE else "black"
        if report.hanging_pieces.get(side):
            return "You have an undefended piece — address that first."

        return None
    except (ValueError, chess.InvalidMoveError):
        return None


def _alternative_moves_text(report: PositionReport) -> str | None:
    """Show alternative candidate moves from MultiPV lines.

    Only shown when there are 2+ lines with moves. Converts UCI to SAN
    and shows the eval difference from the best line.
    """
    if len(report.top_lines) < 2:
        return None

    lines_with_moves = [pv for pv in report.top_lines if pv.moves]
    if len(lines_with_moves) < 2:
        return None

    try:
        board = chess.Board(report.fen)
        best_eval = lines_with_moves[0].eval_cp

        alts = []
        for line in lines_with_moves[1:]:
            move = chess.Move.from_uci(line.moves[0])
            san = board.san(move)
            diff = best_eval - line.eval_cp
            if abs(diff) < 5:
                alts.append(f"{san} (equally good)")
            elif diff > 0:
                alts.append(f"{san} (slightly worse, {diff}cp)")
            else:
                alts.append(f"{san} (also strong)")

        if not alts:
            return None
        return "Other ideas: " + ", ".join(alts) + "."
    except (ValueError, chess.InvalidMoveError):
        return None


def _board_tensions_text(report: PositionReport) -> str | None:
    """Describe key board tensions from the threat map.

    Only mentions squares that are genuinely contested (attacked by both
    sides) or where a piece is under-defended.
    """
    if not report.threat_map:
        return None

    contested = []
    under_defended = []

    for entry in report.threat_map:
        w_atk = entry.white_attackers
        b_atk = entry.black_attackers

        # Genuinely contested: both sides attack the square
        if w_atk > 0 and b_atk > 0:
            contested.append(entry.square)

        # Piece under attack with insufficient defense
        if entry.piece and entry.net_attacked:
            under_defended.append(f"{entry.piece} on {entry.square}")

    parts = []
    if under_defended:
        parts.append("Under-defended: " + ", ".join(under_defended))
    if contested:
        squares = ", ".join(contested)
        parts.append(f"Contested squares: {squares}")

    if not parts:
        return None
    return "Board tensions: " + ". ".join(parts) + "."
