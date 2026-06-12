"""Layer 3 — human calibration.

Measures whether the Layer 2 judge agrees with a human on a seed set.
If agreement is high, we trust the judge on unreviewed positions; if
not, the rubric wording or judge model needs work before the
coaching-quality scores mean anything.

This module is pure post-processing: it compares per-criterion
pass/fail from the judge (already recorded in a run's results.json)
against human ratings (a YAML sidecar). No engine, no LLM here — the
judging happened in the eval run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .judge import JudgeRubric

# Default: a judge that agrees with the human on at least this share
# of per-criterion calls is trusted for unreviewed positions.
DEFAULT_AGREEMENT_THRESHOLD = 0.8


def response_key(position_id: str, model: str) -> str:
    """Stable key for one (position, model) coaching response. Used to
    line up human ratings with judge verdicts."""
    return f"{position_id}::{model}"


@dataclass
class AgreementReport:
    n: int  # number of (position, model) pairs rated by BOTH human and judge
    per_criterion: dict[str, float]
    overall: float
    below_threshold: list[str]
    threshold: float
    missing: list[str] = field(default_factory=list)  # keys rated by only one side

    @property
    def ok(self) -> bool:
        return self.n > 0 and not self.below_threshold


def compute_agreement(
    human: dict[str, dict[str, bool]],
    judge: dict[str, dict[str, bool]],
    rubric: JudgeRubric,
    *,
    threshold: float = DEFAULT_AGREEMENT_THRESHOLD,
) -> AgreementReport:
    """Per-criterion and overall agreement between human and judge.

    Only keys present in *both* maps are compared; keys rated by just
    one side are reported in ``missing`` (so a half-finished rating
    file is visible, not silently averaged in)."""
    shared = sorted(set(human) & set(judge))
    only_one = sorted(set(human) ^ set(judge))

    per_criterion: dict[str, float] = {}
    total_cells = 0
    total_agree = 0
    for ck in rubric.keys():
        agree = sum(1 for k in shared if human[k].get(ck) == judge[k].get(ck))
        per_criterion[ck] = round(agree / len(shared), 4) if shared else 0.0
        total_cells += len(shared)
        total_agree += agree

    overall = round(total_agree / total_cells, 4) if total_cells else 0.0
    below = [ck for ck in rubric.keys() if per_criterion[ck] < threshold]
    return AgreementReport(
        n=len(shared),
        per_criterion=per_criterion,
        overall=overall,
        below_threshold=below,
        threshold=threshold,
        missing=only_one,
    )


def load_seed_ratings(path: str | Path) -> dict[str, dict[str, bool]]:
    """Load human ratings YAML into ``{key: {criterion: bool}}``.

    Shape::

        ratings:
          "starting_position::qwen3:8b":
            key_idea: true
            grounded: false
            ...
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"ratings file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("ratings", {})
    if not isinstance(raw, dict):
        raise ValueError("ratings file: 'ratings' must be a mapping")
    out: dict[str, dict[str, bool]] = {}
    for key, crits in raw.items():
        if not isinstance(crits, dict):
            raise ValueError(f"ratings[{key!r}] must be a mapping of criterion -> bool")
        out[str(key)] = {str(c): bool(v) for c, v in crits.items() if v is not None}
    return out


def build_ratings_template(keys: list[str], rubric: JudgeRubric) -> str:
    """Emit a YAML scaffold the human fills in (null per criterion)."""
    lines = [
        "# Human ratings for judge calibration.",
        "# Set each criterion to true (pass) or false (fail) after",
        "# reading the response + engine findings in the review file.",
        "ratings:",
    ]
    for key in keys:
        lines.append(f'  "{key}":')
        for c in rubric.criteria:
            lines.append(f"    {c.key}: null  # {c.key}")
    return "\n".join(lines) + "\n"
