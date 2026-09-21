"""Classify what actually differs between two runs, before drawing any conclusion from it.

This exists because of a specific mistake on 2026-09-21. Two five-seed sweeps were compared and
60% of the coach's text came back different, which was reported as "the coach is not
reproducible". It was not: 72 of those 81 prompts had changed, because the comparison spanned an
encoding fix. Only 9 turns were comparable, and 8 of those 9 produced identical text. Two further
conclusions were built on the bad one — that a real 8-point regression was noise, and that the
encoding fix had no measurable effect — and both had to be retracted.

The number that would have prevented it had already been printed and was not used. So the fix is
not resolve, it is this: one routine that every comparison goes through, which separates the
turns whose INPUT changed from the turns where only the OUTPUT changed.

Three outcomes per turn, and the distinction is the whole point:

- ``SAME`` — same prompt, same text. Nothing happened.
- ``MODEL`` — same prompt, DIFFERENT text. The only honest measurement of model
  non-determinism, because it is the only case where the input was held fixed.
- ``INPUT`` — the prompt changed. Whatever the text does here is attributable to our code, and
  saying "that is just noise" about one of these is exactly the error above.

A difference is only noise if it lands in ``MODEL``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: Per-turn verdicts. Strings rather than an enum so they survive JSON and print readably.
SAME = "same"
MODEL = "model"
INPUT = "input"


@dataclass(frozen=True)
class TurnIO:
    """What one turn sent to the model and got back."""

    ply: int
    prompt: str
    text: str

    @property
    def spoke(self) -> bool:
        return bool(self.text.strip())


@dataclass
class Comparison:
    """Turn-level attribution for one pair of runs."""

    left: str
    right: str
    same: list[int] = field(default_factory=list)
    model: list[int] = field(default_factory=list)
    input_changed: list[int] = field(default_factory=list)
    only_left: list[int] = field(default_factory=list)
    only_right: list[int] = field(default_factory=list)

    @property
    def comparable(self) -> int:
        """Turns where the input was held fixed — the only ones that can show noise."""
        return len(self.same) + len(self.model)

    @property
    def noise_turns(self) -> int:
        return len(self.model)

    @property
    def is_repeat(self) -> bool:
        """True when nothing about the input differed, so the pair is a genuine repeat."""
        return not self.input_changed and not self.only_left and not self.only_right

    def summary(self) -> str:
        parts = [
            f"{self.left} vs {self.right}:",
            f"{len(self.same)} identical,",
            f"{len(self.model)} same prompt but different text,",
            f"{len(self.input_changed)} prompt changed",
        ]
        if self.only_left or self.only_right:
            parts.append(f"(+{len(self.only_left)}/{len(self.only_right)} turns present on one side only)")
        return " ".join(parts)

    def verdict(self) -> str:
        """One line the caller can print instead of guessing whether a difference is noise."""
        if self.input_changed:
            return (
                f"NOT a repeat: {len(self.input_changed)} of {len(self.input_changed) + self.comparable} "
                f"turns changed their PROMPT. Differences on those turns are attributable to the code "
                f"change, not to model noise. Only {self.comparable} turns are comparable, and "
                f"{len(self.model)} of those differ."
            )
        if self.model:
            return (
                f"Genuine repeat. {len(self.model)} of {self.comparable} turns differ with an identical "
                f"prompt, so that is the model's own non-determinism: plies {self.model}."
            )
        return f"Genuine repeat, and byte-identical on all {self.comparable} turns."


def load_turns(transcript: Path) -> dict[int, TurnIO]:
    """Prompt and coach text per ply, from a report-card transcript."""
    data = json.loads(Path(transcript).read_text(encoding="utf-8"))
    out: dict[int, TurnIO] = {}
    for t in data.get("turns", []):
        ply = t.get("ply")
        if not isinstance(ply, int):
            continue
        out[ply] = TurnIO(ply=ply, prompt=t.get("prompt") or "", text=(t.get("coach_feedback") or "").strip())
    return out


def compare(left: Path, right: Path) -> Comparison:
    """Attribute every turn's difference to the input or to the model.

    Turns where BOTH sides are silent are skipped entirely: the coach said nothing either time
    and there is no prompt, so counting them inflates the "identical" figure with turns that were
    never a measurement. That inflation is how a comparison can look stable while every spoken
    turn moved.
    """
    a, b = load_turns(left), load_turns(right)
    out = Comparison(left=Path(left).parent.name, right=Path(right).parent.name)
    for ply in sorted(set(a) | set(b)):
        ta, tb = a.get(ply), b.get(ply)
        if ta is None:
            if tb is not None and (tb.spoke or tb.prompt):
                out.only_right.append(ply)
            continue
        if tb is None:
            if ta.spoke or ta.prompt:
                out.only_left.append(ply)
            continue
        if not (ta.prompt or tb.prompt or ta.spoke or tb.spoke):
            continue
        if ta.prompt != tb.prompt:
            out.input_changed.append(ply)
        elif ta.text != tb.text:
            out.model.append(ply)
        else:
            out.same.append(ply)
    return out


def partition_repeats(paths: list[Path]) -> tuple[list[Path], list[tuple[Path, Comparison]]]:
    """``(repeats, rejected)`` — runs whose prompts all match the first, and those that do not.

    The first path is the reference. Rejecting rather than silently pooling is the point: a run
    with a different prompt is a different experiment, and averaging it in is what produced the
    retracted "60% not reproducible" number.
    """
    if not paths:
        return [], []
    reference = paths[0]
    keep = [reference]
    rejected: list[tuple[Path, Comparison]] = []
    for path in paths[1:]:
        cmp_ = compare(reference, path)
        if cmp_.is_repeat:
            keep.append(path)
        else:
            rejected.append((path, cmp_))
    return keep, rejected
