"""Tests for pairwise judging (Task 6.3 / Property 6) + judge auth."""

from __future__ import annotations

import json
import random

from chess_coach.eval.benchmark import BenchmarkPosition, GroundTruthPoint
from chess_coach.eval.judge import (
    build_pairwise_prompt,
    pairwise_compare,
    parse_pairwise,
)
from chess_coach.llm.openai_compat import OpenAICompatProvider
from chess_coach.models import EvalBreakdown, KingSafety, PawnFeatures, PositionReport

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _report() -> PositionReport:
    return PositionReport(
        fen=START_FEN,
        eval_cp=0,
        eval_breakdown=EvalBreakdown(0, 0, 0, 0),
        hanging_pieces={"white": [], "black": []},
        threats={"white": [], "black": []},
        pawn_structure={"white": PawnFeatures([], [], []), "black": PawnFeatures([], [], [])},
        king_safety={"white": KingSafety(0, ""), "black": KingSafety(0, "")},
        top_lines=[],
        tactics=[],
        threat_map=[],
        threat_map_summary=None,
        critical_moment=False,
        critical_reason=None,
    )


def _pos() -> BenchmarkPosition:
    return BenchmarkPosition(
        id="t",
        fen=START_FEN,
        level="beginner",
        phase="opening",
        points=(GroundTruthPoint("free", "center"),),
    )


class _SlotJudge:
    """Always picks the response in slot ``winner_slot`` and records the
    prompts it saw so we can check which response came first."""

    def __init__(self, winner_slot: str):
        self.winner_slot = winner_slot
        self.model = "slot-judge"
        self.last_prompt = ""

    def generate(self, prompt: str, max_tokens: int = 400, temperature: float = 0.0) -> str:
        self.last_prompt = prompt
        return json.dumps({"winner": self.winner_slot, "reason": "test"})


# --------------------------------------------------------------- parse


def test_parse_pairwise() -> None:
    assert parse_pairwise('{"winner": "1", "reason": "x"}')[0] == "1"
    assert parse_pairwise('{"winner": "tie", "reason": "x"}')[0] == "tie"


def test_build_pairwise_prompt_has_both_responses() -> None:
    p = build_pairwise_prompt("ALPHA", "BETA", _report(), _pos())
    assert "ALPHA" in p and "BETA" in p
    assert "GROUND TRUTH" in p


# --------------------------------------------------------------- P6: order randomized + recorded


def test_pairwise_order_randomized_and_recorded() -> None:
    judge = _SlotJudge("1")  # always picks whoever is shown first
    # Across many seeds we should see BOTH orderings, and each result
    # records which model was shown first (auditable).
    first_shown_seen = set()
    for seed in range(20):
        r = pairwise_compare(judge, "A", "respA", "B", "respB", _report(), _pos(), rng=random.Random(seed))
        assert r.first_shown in ("A", "B")
        first_shown_seen.add(r.first_shown)
    assert first_shown_seen == {"A", "B"}


def test_pairwise_winner_maps_back_to_model() -> None:
    # Judge always says slot 1 wins; whoever was shown first should win.
    judge = _SlotJudge("1")
    for seed in range(8):
        r = pairwise_compare(judge, "A", "respA", "B", "respB", _report(), _pos(), rng=random.Random(seed))
        assert r.winner == r.first_shown


def test_pairwise_tie() -> None:
    judge = _SlotJudge("tie")
    r = pairwise_compare(judge, "A", "respA", "B", "respB", _report(), _pos(), rng=random.Random(1))
    assert r.winner == "tie"


# --------------------------------------------------------------- judge auth


def test_openai_compat_sends_bearer_when_key_given() -> None:
    p = OpenAICompatProvider(model="m", base_url="http://judge", api_key="secret123")
    assert p._client.headers.get("authorization") == "Bearer secret123"


def test_openai_compat_no_auth_header_without_key() -> None:
    p = OpenAICompatProvider(model="m", base_url="http://judge")
    assert "authorization" not in p._client.headers
