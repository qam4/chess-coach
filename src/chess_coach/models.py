"""Coaching protocol data models, error hierarchy, and validation.

Frozen dataclasses for structured engine evaluation data, with JSON
round-trip support via to_dict() / from_dict() class methods.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class CoachingProtocolError(Exception):
    """Base exception for all coaching protocol errors."""


class CoachingTimeoutError(CoachingProtocolError):
    """Raised when a coaching command exceeds its timeout."""


class CoachingParseError(CoachingProtocolError):
    """Raised when the engine returns malformed JSON."""


class CoachingValidationError(CoachingProtocolError):
    """Raised when JSON does not conform to the expected schema."""


class EngineTerminatedError(CoachingProtocolError):
    """Raised when the engine process terminates unexpectedly."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalBreakdown:
    material: int
    mobility: int
    king_safety: int
    pawn_structure: int
    tempo: int = 0
    piece_bonuses: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "material": self.material,
            "mobility": self.mobility,
            "king_safety": self.king_safety,
            "pawn_structure": self.pawn_structure,
            "tempo": self.tempo,
            "piece_bonuses": self.piece_bonuses,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EvalBreakdown:
        return cls(
            material=d["material"],
            mobility=d["mobility"],
            king_safety=d["king_safety"],
            pawn_structure=d["pawn_structure"],
            tempo=d.get("tempo", 0),
            piece_bonuses=d.get("piece_bonuses", 0),
        )


@dataclass(frozen=True)
class HangingPiece:
    square: str
    piece: str
    color: str

    def to_dict(self) -> dict[str, Any]:
        return {"square": self.square, "piece": self.piece, "color": self.color}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HangingPiece:
        return cls(square=d["square"], piece=d["piece"], color=d.get("color", ""))


@dataclass(frozen=True)
class Threat:
    type: str
    source_square: str
    target_squares: list[str]
    description: str
    uci_move: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "source_square": self.source_square,
            "target_squares": list(self.target_squares),
            "description": self.description,
            "uci_move": self.uci_move,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Threat:
        return cls(
            type=d["type"],
            source_square=d["source_square"],
            target_squares=list(d["target_squares"]),
            description=d["description"],
            uci_move=d.get("uci_move", ""),
        )


@dataclass(frozen=True)
class PawnFeatures:
    isolated: list[str]
    doubled: list[str]
    passed: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "isolated": list(self.isolated),
            "doubled": list(self.doubled),
            "passed": list(self.passed),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PawnFeatures:
        return cls(
            isolated=list(d["isolated"]),
            doubled=list(d["doubled"]),
            passed=list(d["passed"]),
        )


@dataclass(frozen=True)
class KingSafety:
    score: int
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KingSafety:
        return cls(score=d["score"], description=d["description"])


@dataclass(frozen=True)
class TacticalMotif:
    type: str
    squares: list[str]
    pieces: list[str]
    in_pv: bool
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "squares": list(self.squares),
            "pieces": list(self.pieces),
            "in_pv": self.in_pv,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TacticalMotif:
        return cls(
            type=d["type"],
            squares=list(d["squares"]),
            pieces=list(d["pieces"]),
            in_pv=d["in_pv"],
            description=d["description"],
        )


@dataclass(frozen=True)
class ThreatMapEntry:
    square: str
    piece: str | None
    white_attackers: int
    black_attackers: int
    white_defenders: int
    black_defenders: int
    net_attacked: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "square": self.square,
            "piece": self.piece,
            "white_attackers": self.white_attackers,
            "black_attackers": self.black_attackers,
            "white_defenders": self.white_defenders,
            "black_defenders": self.black_defenders,
            "net_attacked": self.net_attacked,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ThreatMapEntry:
        return cls(
            square=d["square"],
            piece=d["piece"],
            white_attackers=d["white_attackers"],
            black_attackers=d["black_attackers"],
            white_defenders=d["white_defenders"],
            black_defenders=d["black_defenders"],
            net_attacked=d["net_attacked"],
        )


@dataclass(frozen=True)
class PVLine:
    depth: int
    eval_cp: int
    moves: list[str]
    theme: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "depth": self.depth,
            "eval_cp": self.eval_cp,
            "moves": list(self.moves),
            "theme": self.theme,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PVLine:
        return cls(
            depth=d["depth"],
            eval_cp=d["eval_cp"],
            moves=list(d["moves"]),
            theme=d["theme"],
        )


@dataclass(frozen=True)
class PositionReport:
    fen: str
    eval_cp: int
    eval_breakdown: EvalBreakdown
    hanging_pieces: dict[str, list[HangingPiece]]
    threats: dict[str, list[Threat]]
    pawn_structure: dict[str, PawnFeatures]
    king_safety: dict[str, KingSafety]
    top_lines: list[PVLine]
    tactics: list[TacticalMotif]
    threat_map: list[ThreatMapEntry]
    threat_map_summary: str | None
    critical_moment: bool
    critical_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fen": self.fen,
            "eval_cp": self.eval_cp,
            "eval_breakdown": self.eval_breakdown.to_dict(),
            "hanging_pieces": {side: [hp.to_dict() for hp in pieces] for side, pieces in self.hanging_pieces.items()},
            "threats": {side: [t.to_dict() for t in threats] for side, threats in self.threats.items()},
            "pawn_structure": {side: pf.to_dict() for side, pf in self.pawn_structure.items()},
            "king_safety": {side: ks.to_dict() for side, ks in self.king_safety.items()},
            "top_lines": [line.to_dict() for line in self.top_lines],
            "tactics": [t.to_dict() for t in self.tactics],
            "threat_map": [e.to_dict() for e in self.threat_map],
            "threat_map_summary": self.threat_map_summary,
            "critical_moment": self.critical_moment,
            "critical_reason": self.critical_reason,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PositionReport:
        return cls(
            fen=d["fen"],
            eval_cp=d["eval_cp"],
            eval_breakdown=EvalBreakdown.from_dict(d["eval_breakdown"]),
            hanging_pieces={
                side: [HangingPiece.from_dict(hp) for hp in pieces] for side, pieces in d["hanging_pieces"].items()
            },
            threats={side: [Threat.from_dict(t) for t in threats] for side, threats in d["threats"].items()},
            pawn_structure={side: PawnFeatures.from_dict(pf) for side, pf in d["pawn_structure"].items()},
            king_safety={side: KingSafety.from_dict(ks) for side, ks in d["king_safety"].items()},
            top_lines=[PVLine.from_dict(line) for line in d["top_lines"]],
            tactics=[TacticalMotif.from_dict(t) for t in d["tactics"]],
            threat_map=[ThreatMapEntry.from_dict(e) for e in d["threat_map"]],
            threat_map_summary=d.get("threat_map_summary"),
            critical_moment=d["critical_moment"],
            critical_reason=d["critical_reason"],
        )


@dataclass(frozen=True)
class ComparisonReport:
    fen: str
    user_move: str
    user_eval_cp: int
    best_move: str
    best_eval_cp: int
    eval_drop_cp: int
    classification: str
    nag: str
    best_move_idea: str
    refutation_line: list[str] | None
    missed_tactics: list[TacticalMotif]
    top_lines: list[PVLine]
    critical_moment: bool
    critical_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fen": self.fen,
            "user_move": self.user_move,
            "user_eval_cp": self.user_eval_cp,
            "best_move": self.best_move,
            "best_eval_cp": self.best_eval_cp,
            "eval_drop_cp": self.eval_drop_cp,
            "classification": self.classification,
            "nag": self.nag,
            "best_move_idea": self.best_move_idea,
            "refutation_line": (list(self.refutation_line) if self.refutation_line is not None else None),
            "missed_tactics": [t.to_dict() for t in self.missed_tactics],
            "top_lines": [line.to_dict() for line in self.top_lines],
            "critical_moment": self.critical_moment,
            "critical_reason": self.critical_reason,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ComparisonReport:
        ref_line = d["refutation_line"]
        return cls(
            fen=d["fen"],
            user_move=d["user_move"],
            user_eval_cp=d["user_eval_cp"],
            best_move=d["best_move"],
            best_eval_cp=d["best_eval_cp"],
            eval_drop_cp=d["eval_drop_cp"],
            classification=d["classification"],
            nag=d["nag"],
            best_move_idea=d["best_move_idea"],
            refutation_line=list(ref_line) if ref_line is not None else None,
            missed_tactics=[TacticalMotif.from_dict(t) for t in d["missed_tactics"]],
            top_lines=[PVLine.from_dict(line) for line in d["top_lines"]],
            critical_moment=d["critical_moment"],
            critical_reason=d["critical_reason"],
        )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_key(data: dict[str, Any], key: str, expected_type: type, context: str = "") -> Any:
    """Check that *key* exists in *data* and has the right type."""
    prefix = f"{context}.{key}" if context else key
    if key not in data:
        raise CoachingValidationError(f"missing required field: {prefix}")
    value = data[key]
    if not isinstance(value, expected_type):
        raise CoachingValidationError(f"field {prefix}: expected {expected_type.__name__}, got {type(value).__name__}")
    return value


def _require_key_nullable(data: dict[str, Any], key: str, expected_type: type, context: str = "") -> Any:
    """Like _require_key but allows None."""
    prefix = f"{context}.{key}" if context else key
    if key not in data:
        raise CoachingValidationError(f"missing required field: {prefix}")
    value = data[key]
    if value is not None and not isinstance(value, expected_type):
        raise CoachingValidationError(
            f"field {prefix}: expected {expected_type.__name__} or None, got {type(value).__name__}"
        )
    return value


def _require_dict(data: Any, context: str) -> None:
    """Raise if *data* is not a dict."""
    if not isinstance(data, dict):
        raise CoachingValidationError(f"field {context}: expected object, got {type(data).__name__}")


def _validate_eval_breakdown(data: Any, ctx: str = "eval_breakdown") -> None:
    _require_dict(data, ctx)
    for field in ("material", "mobility", "king_safety", "pawn_structure"):
        _require_key(data, field, int, ctx)


def _validate_hanging_piece(data: Any, ctx: str = "hanging_piece") -> None:
    _require_dict(data, ctx)
    for field in ("square", "piece"):
        _require_key(data, field, str, ctx)
    # 'color' is optional — inferred from the parent side key when missing
    if "color" in data:
        _require_key(data, "color", str, ctx)


def _validate_threat(data: Any, ctx: str = "threat") -> None:
    _require_dict(data, ctx)
    _require_key(data, "type", str, ctx)
    _require_key(data, "source_square", str, ctx)
    _require_key(data, "target_squares", list, ctx)
    _require_key(data, "description", str, ctx)


def _validate_pawn_features(data: Any, ctx: str = "pawn_features") -> None:
    _require_dict(data, ctx)
    for field in ("isolated", "doubled", "passed"):
        _require_key(data, field, list, ctx)


def _validate_king_safety(data: Any, ctx: str = "king_safety") -> None:
    _require_dict(data, ctx)
    _require_key(data, "score", int, ctx)
    _require_key(data, "description", str, ctx)


def _validate_tactical_motif(data: Any, ctx: str = "tactical_motif") -> None:
    _require_dict(data, ctx)
    _require_key(data, "type", str, ctx)
    _require_key(data, "squares", list, ctx)
    _require_key(data, "pieces", list, ctx)
    _require_key(data, "in_pv", bool, ctx)
    _require_key(data, "description", str, ctx)


def _validate_threat_map_entry(data: Any, ctx: str = "threat_map_entry") -> None:
    _require_dict(data, ctx)
    _require_key(data, "square", str, ctx)
    _require_key_nullable(data, "piece", str, ctx)
    for field in (
        "white_attackers",
        "black_attackers",
        "white_defenders",
        "black_defenders",
    ):
        _require_key(data, field, int, ctx)
    _require_key(data, "net_attacked", bool, ctx)


def _validate_pv_line(data: Any, ctx: str = "pv_line") -> None:
    _require_dict(data, ctx)
    _require_key(data, "depth", int, ctx)
    _require_key(data, "eval_cp", int, ctx)
    _require_key(data, "moves", list, ctx)
    _require_key(data, "theme", str, ctx)


def _validate_side_dict(
    data: Any,
    key: str,
    item_validator: Any,
    context: str = "",
) -> None:
    """Validate a dict with 'white' and 'black' keys."""
    prefix = f"{context}.{key}" if context else key
    _require_dict(data, prefix)
    for side in ("white", "black"):
        if side not in data:
            raise CoachingValidationError(f"missing required field: {prefix}.{side}")
        side_data = data[side]
        if isinstance(side_data, list):
            for i, item in enumerate(side_data):
                item_validator(item, f"{prefix}.{side}[{i}]")
        else:
            item_validator(side_data, f"{prefix}.{side}")


# ---------------------------------------------------------------------------
# Public validation functions
# ---------------------------------------------------------------------------


def validate_position_report(data: dict[str, Any]) -> PositionReport:
    """Validate a raw dict and return a typed PositionReport.

    Raises CoachingValidationError with the offending field name on failure.
    """
    _require_key(data, "fen", str)
    _require_key(data, "eval_cp", int)

    _require_key(data, "eval_breakdown", dict)
    _validate_eval_breakdown(data["eval_breakdown"])

    _require_key(data, "hanging_pieces", dict)
    # Backfill 'color' from the side key when the engine omits it
    for side in ("white", "black"):
        for hp in data["hanging_pieces"].get(side, []):
            if isinstance(hp, dict) and "color" not in hp:
                hp["color"] = side
    _validate_side_dict(data["hanging_pieces"], "hanging_pieces", _validate_hanging_piece)

    _require_key(data, "threats", dict)
    _validate_side_dict(data["threats"], "threats", _validate_threat)

    _require_key(data, "pawn_structure", dict)
    _validate_side_dict(data["pawn_structure"], "pawn_structure", _validate_pawn_features)

    _require_key(data, "king_safety", dict)
    _validate_side_dict(data["king_safety"], "king_safety", _validate_king_safety)

    top_lines = _require_key(data, "top_lines", list)
    for i, line in enumerate(top_lines):
        _validate_pv_line(line, f"top_lines[{i}]")

    tactics = _require_key(data, "tactics", list)
    for i, t in enumerate(tactics):
        _validate_tactical_motif(t, f"tactics[{i}]")

    threat_map = _require_key(data, "threat_map", list)
    for i, entry in enumerate(threat_map):
        _validate_threat_map_entry(entry, f"threat_map[{i}]")

    # threat_map_summary is optional (new in Blunder coaching protocol)

    _require_key(data, "critical_moment", bool)
    _require_key_nullable(data, "critical_reason", str)

    return PositionReport.from_dict(data)


def validate_comparison_report(data: dict[str, Any]) -> ComparisonReport:
    """Validate a raw dict and return a typed ComparisonReport.

    Raises CoachingValidationError with the offending field name on failure.
    """
    _require_key(data, "fen", str)
    _require_key(data, "user_move", str)
    _require_key(data, "user_eval_cp", int)
    _require_key(data, "best_move", str)
    _require_key(data, "best_eval_cp", int)
    _require_key(data, "eval_drop_cp", int)
    _require_key(data, "classification", str)
    _require_key(data, "nag", str)
    _require_key(data, "best_move_idea", str)
    _require_key_nullable(data, "refutation_line", list)

    missed = _require_key(data, "missed_tactics", list)
    for i, t in enumerate(missed):
        _validate_tactical_motif(t, f"missed_tactics[{i}]")

    top_lines = _require_key(data, "top_lines", list)
    for i, line in enumerate(top_lines):
        _validate_pv_line(line, f"top_lines[{i}]")

    _require_key(data, "critical_moment", bool)
    _require_key_nullable(data, "critical_reason", str)

    return ComparisonReport.from_dict(data)


# ---------------------------------------------------------------------------
# NAG computation
# ---------------------------------------------------------------------------


def compute_nag(eval_drop_cp: int, user_move: str, best_move: str) -> str:
    """Compute the NAG (Numeric Annotation Glyph) for a move.

    Args:
        eval_drop_cp: Centipawn evaluation drop (best_eval - user_eval).
        user_move: The move the user played (UCI notation).
        best_move: The engine's best move (UCI notation).

    Returns:
        A NAG string: ``"!!"`, ``"!"``, ``"!?"``, ``"?!"``, ``"?"``, or ``"??"``.

    The mapping follows standard thresholds:
        - ``!!``  brilliant — user played the best move with no eval loss
        - ``!``   good — eval drop ≤ 10 cp (or user played best move)
        - ``!?``  interesting — eval drop 11–30 cp
        - ``?!``  dubious — eval drop 31–100 cp
        - ``?``   mistake — eval drop 101–300 cp
        - ``??``  blunder — eval drop > 300 cp

    When *user_move* equals *best_move*, the result is always ``!`` or
    ``!!`` regardless of the absolute eval.
    """
    if user_move == best_move:
        return "!!" if eval_drop_cp <= 0 else "!"

    if eval_drop_cp <= 10:
        return "!"
    if eval_drop_cp <= 30:
        return "!?"
    if eval_drop_cp <= 100:
        return "?!"
    if eval_drop_cp <= 300:
        return "?"
    return "??"


# ---------------------------------------------------------------------------
# Coaching command formatting
# ---------------------------------------------------------------------------


def format_coaching_command(cmd_type: str, **params: object) -> str:
    """Format a coaching protocol command string.

    Produces a single-line command starting with ``coach `` followed by the
    command type and any parameters.

    Supported commands::

        format_coaching_command("ping")
        # -> "coach ping"

        format_coaching_command("eval", fen="rnbq.../... w KQkq - 0 1", multipv=3)
        # -> "coach eval fen rnbq.../... w KQkq - 0 1 multipv 3"

        format_coaching_command("compare", fen="rnbq.../... w KQkq - 0 1", move="e2e4")
        # -> "coach compare fen rnbq.../... w KQkq - 0 1 move e2e4"

    Args:
        cmd_type: One of ``"eval"``, ``"compare"``, or ``"ping"``.
        **params: Command-specific keyword arguments.

    Returns:
        A single-line string ready to be written to the engine's stdin.

    Raises:
        ValueError: If *cmd_type* is not recognised or required parameters
            are missing.
    """
    if cmd_type == "ping":
        return "coach ping"

    if cmd_type == "eval":
        fen = params.get("fen")
        if fen is None:
            raise ValueError("'eval' command requires a 'fen' parameter")
        parts = [f"coach eval fen {fen}"]
        multipv = params.get("multipv")
        if multipv is not None:
            parts.append(f"multipv {multipv}")
        depth = params.get("depth")
        if depth is not None:
            parts.append(f"depth {depth}")
        movetime = params.get("movetime")
        if movetime is not None:
            parts.append(f"movetime {movetime}")
        return " ".join(parts)

    if cmd_type == "compare":
        fen = params.get("fen")
        move = params.get("move")
        if fen is None:
            raise ValueError("'compare' command requires a 'fen' parameter")
        if move is None:
            raise ValueError("'compare' command requires a 'move' parameter")
        parts = [f"coach compare fen {fen} move {move}"]
        depth = params.get("depth")
        if depth is not None:
            parts.append(f"depth {depth}")
        movetime = params.get("movetime")
        if movetime is not None:
            parts.append(f"movetime {movetime}")
        return " ".join(parts)

    raise ValueError(f"unknown coaching command type: {cmd_type!r}")


# ---------------------------------------------------------------------------
# Response marker extraction and JSON parsing
# ---------------------------------------------------------------------------

# Markers that delimit a coaching protocol response in the engine's stdout.
_BEGIN_MARKER = "BEGIN_COACH_RESPONSE"
_END_MARKER = "END_COACH_RESPONSE"

# Maximum length of raw text included in error messages.
_RAW_TEXT_LIMIT = 500


def parse_coaching_response(lines: list[str]) -> dict[str, Any]:
    """Extract and parse a coaching protocol JSON response from engine output.

    The engine wraps every coaching response in marker lines::

        BEGIN_COACH_RESPONSE
        {"protocol": "coaching", "version": "1.0.0", "type": "...", "data": {...}}
        END_COACH_RESPONSE

    This function:

    1. Finds the lines between the ``BEGIN_COACH_RESPONSE`` and
       ``END_COACH_RESPONSE`` markers.
    2. Joins those lines and parses the result as JSON.
    3. Checks that the envelope contains ``"protocol": "coaching"``.
    4. Returns the ``"data"`` dict from the envelope.

    Args:
        lines: Raw lines read from the engine's stdout (may include
            interleaved UCI info lines outside the markers).

    Returns:
        The ``data`` dict extracted from the coaching response envelope.

    Raises:
        CoachingParseError: If the markers are missing, the content between
            markers is not valid JSON, or the envelope is malformed.
    """
    # --- locate markers ---------------------------------------------------
    begin_idx: int | None = None
    end_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == _BEGIN_MARKER:
            begin_idx = i
        elif stripped == _END_MARKER and begin_idx is not None:
            end_idx = i
            break

    if begin_idx is None or end_idx is None:
        raise CoachingParseError("coaching response markers not found in engine output")

    # --- extract and parse JSON -------------------------------------------
    json_lines = lines[begin_idx + 1 : end_idx]
    raw_text = "\n".join(line.strip() for line in json_lines)

    try:
        envelope = json.loads(raw_text)
    except (json.JSONDecodeError, ValueError) as exc:
        preview = raw_text[:_RAW_TEXT_LIMIT]
        raise CoachingParseError(f"malformed JSON in coaching response: {exc}\n---\n{preview}") from exc

    # --- validate envelope ------------------------------------------------
    if not isinstance(envelope, dict):
        raise CoachingParseError(f"expected JSON object in coaching response, got {type(envelope).__name__}")

    protocol = envelope.get("protocol")
    if protocol != "coaching":
        raise CoachingParseError(f"unexpected protocol field: expected 'coaching', got {protocol!r}")

    if "data" not in envelope:
        raise CoachingParseError("coaching response envelope missing 'data' field")

    # --- check for engine-reported errors ---------------------------------
    resp_type = envelope.get("type")
    if resp_type == "error":
        err_data = envelope["data"]
        code = err_data.get("code", "unknown")
        message = err_data.get("message", "unknown error")
        raise CoachingProtocolError(f"engine error ({code}): {message}")

    data: dict[str, Any] = envelope["data"]
    return data


def parse_coaching_envelope(lines: list[str]) -> dict[str, Any]:
    """Like :func:`parse_coaching_response` but returns the full envelope.

    This is useful when the caller needs envelope-level metadata such as
    ``version`` or ``type`` that are not part of the inner ``data`` dict.

    Returns:
        The complete parsed envelope dict (contains ``protocol``,
        ``version``, ``type``, ``data``, etc.).

    Raises:
        CoachingParseError: Same conditions as :func:`parse_coaching_response`.
    """
    begin_idx: int | None = None
    end_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == _BEGIN_MARKER:
            begin_idx = i
        elif stripped == _END_MARKER and begin_idx is not None:
            end_idx = i
            break

    if begin_idx is None or end_idx is None:
        raise CoachingParseError("coaching response markers not found in engine output")

    json_lines = lines[begin_idx + 1 : end_idx]
    raw_text = "\n".join(line.strip() for line in json_lines)

    try:
        envelope = json.loads(raw_text)
    except (json.JSONDecodeError, ValueError) as exc:
        preview = raw_text[:_RAW_TEXT_LIMIT]
        raise CoachingParseError(f"malformed JSON in coaching response: {exc}\n---\n{preview}") from exc

    if not isinstance(envelope, dict):
        raise CoachingParseError(f"expected JSON object in coaching response, got {type(envelope).__name__}")

    protocol = envelope.get("protocol")
    if protocol != "coaching":
        raise CoachingParseError(f"unexpected protocol field: expected 'coaching', got {protocol!r}")

    return envelope


# ---------------------------------------------------------------------------
# Version compatibility checking
# ---------------------------------------------------------------------------


def check_version_compatibility(engine_version: str, expected_version: str) -> str:
    """Check whether the engine's protocol version is compatible with the expected version.

    Parses two semver strings (``"major.minor.patch"``) and applies the
    following rules:

    * Different major versions → ``"incompatible"`` (breaking change).
    * Same major, engine minor > expected minor → ``"compatible_warning"``
      (backward-compatible additions in the engine).
    * Same major, engine minor < expected minor → ``"incompatible"``
      (engine is older than expected).
    * Same major and minor, only patch differs → ``"compatible"``.

    Args:
        engine_version: The version string reported by the engine
            (e.g. ``"1.2.3"``).
        expected_version: The version string the client expects
            (e.g. ``"1.0.0"``).

    Returns:
        One of ``"compatible"``, ``"compatible_warning"``, or
        ``"incompatible"``.

    Raises:
        ValueError: If either version string is not a valid semver triplet.
    """

    def _parse(version: str) -> tuple[int, int, int]:
        parts = version.strip().split(".")
        if len(parts) != 3:
            raise ValueError(f"invalid semver string: {version!r}")
        try:
            return int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            raise ValueError(f"invalid semver string: {version!r}") from None

    eng_major, eng_minor, _eng_patch = _parse(engine_version)
    exp_major, exp_minor, _exp_patch = _parse(expected_version)

    if eng_major != exp_major:
        return "incompatible"

    if eng_minor > exp_minor:
        return "compatible_warning"

    if eng_minor < exp_minor:
        return "incompatible"

    # Same major and minor — patch-only difference (or identical).
    return "compatible"
