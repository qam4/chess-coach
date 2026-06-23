"""Tests for pairwise judging (Task 6.3 / Property 6) + judge auth."""

from __future__ import annotations

import json
import random

from chess_coach.eval.benchmark import BenchmarkPosition, GroundTruthPoint
from chess_coach.eval.judge import (
    build_pairwise_prompt,
    majority_winner,
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


# ----------------------------------------------------- majority_winner (repeats)


class TestMajorityWinner:
    """Reducing repeated judgments of the same pair to one verdict."""

    def test_clear_majority_on(self) -> None:
        winner, counts = majority_winner(["on", "on", "off"], "off", "on")
        assert winner == "on"
        assert counts == {"off": 1, "on": 2, "tie": 0}

    def test_clear_majority_off(self) -> None:
        winner, counts = majority_winner(["off", "off", "on"], "off", "on")
        assert winner == "off"

    def test_exact_split_is_tie(self) -> None:
        winner, _ = majority_winner(["off", "on"], "off", "on")
        assert winner == "tie"

    def test_ties_do_not_decide(self) -> None:
        # Equal off/on with extra ties stays a tie.
        winner, counts = majority_winner(["off", "on", "tie", "tie"], "off", "on")
        assert winner == "tie"
        assert counts["tie"] == 2

    def test_tie_votes_break_toward_plurality(self) -> None:
        # A plurality for "on" wins even when ties are present.
        winner, _ = majority_winner(["on", "on", "tie"], "off", "on")
        assert winner == "on"

    def test_empty_is_tie(self) -> None:
        winner, counts = majority_winner([], "off", "on")
        assert winner == "tie"
        assert counts == {"off": 0, "on": 0, "tie": 0}

    def test_single_vote(self) -> None:
        assert majority_winner(["on"], "off", "on")[0] == "on"


# ------------------------------------------------ judge JSON parsing robustness


class TestPairwiseParseRobustness:
    """parse_pairwise tolerates the malformed replies that lost situations."""

    def test_plain_json(self) -> None:
        winner, reason = parse_pairwise('{"winner": "1", "reason": "clear"}')
        assert winner == "1"
        assert reason == "clear"

    def test_control_character_in_reason(self) -> None:
        # A raw newline inside the reason string previously raised
        # "Invalid control character" — strict=False now tolerates it.
        winner, reason = parse_pairwise('{"winner": "2", "reason": "line one\nline two"}')
        assert winner == "2"
        assert "line one" in reason

    def test_trailing_prose_after_object(self) -> None:
        # Trailing text after the JSON previously raised "Extra data".
        reply = '{"winner": "1", "reason": "best"}\n\nHope that helps!'
        winner, _ = parse_pairwise(reply)
        assert winner == "1"

    def test_markdown_fenced(self) -> None:
        reply = '```json\n{"winner": "tie", "reason": "even"}\n```'
        winner, _ = parse_pairwise(reply)
        assert winner == "tie"

    def test_brace_inside_reason_string(self) -> None:
        winner, reason = parse_pairwise('{"winner": "2", "reason": "use {x} notation"}')
        assert winner == "2"
        assert "{x}" in reason
