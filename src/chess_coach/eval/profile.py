"""Model-capability profiler — pure core.

Data model + threshold→recommendation mapping + rendering for the profiler.
This module is the **pure layer**: no engine, no network, no live model. The
live producer (running the evals, reading the numbers) is a thin step on top,
wired separately in ``scripts/profile_model.py``.

Design commitments (see ``.kiro/specs/model-capability-profiler/``):

* **Facts, not verdicts.** A :class:`DimensionResult` carries raw ``metrics``
  and (separately) ``latency_s``; the only place facts become advice is
  :func:`recommend`, which is small and isolated. Latency never gets a
  pass/fail.
* **Capability and cost are separate fields.** ``metrics`` (quality) and
  ``latency_s`` (cost) sit side by side, never blended.
* **Operator-in-the-loop.** :func:`recommend` returns *advice*; nothing here
  writes config.
* **Dimensions are a list, not a schema.** Adding a dimension is appending a
  :class:`DimensionResult`; the renderer and mapping iterate the list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# --------------------------------------------------------------- data model


@dataclass(frozen=True)
class DimensionResult:
    """One measured coaching dimension for a model.

    ``metrics`` holds raw quality facts (e.g. ``{"factual": 0.30,
    "hallucinations": 0}``); ``latency_s`` holds the cost fact separately so
    the two are never blended. ``status`` is ``"pass"``/``"fail"`` for graded
    dimensions or ``"info"`` for fact-only ones (e.g. latency).
    """

    name: str
    status: str  # "pass" | "fail" | "info"
    metrics: dict[str, float] = field(default_factory=dict)
    latency_s: float | None = None
    samples: int = 0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "name": self.name,
            "status": self.status,
            "metrics": dict(self.metrics),
            "latency_s": self.latency_s,
            "samples": self.samples,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DimensionResult:
        """Build a DimensionResult from its dict form."""
        return cls(
            name=d["name"],
            status=d["status"],
            metrics={k: float(v) for k, v in d.get("metrics", {}).items()},
            latency_s=d.get("latency_s"),
            samples=int(d.get("samples", 0)),
            notes=d.get("notes", ""),
        )


@dataclass(frozen=True)
class CapabilityProfile:
    """A per-model profile: a list of dimension results plus provenance.

    Dimensions are a list (a menu, not a schema) so adding one later is an
    append, not a data-model change.
    """

    model: str
    captured_at: datetime
    dimensions: list[DimensionResult] = field(default_factory=list)

    def dimension(self, name: str) -> DimensionResult | None:
        """Return the dimension result with ``name``, or None if absent."""
        for d in self.dimensions:
            if d.name == name:
                return d
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "model": self.model,
            "captured_at": self.captured_at.isoformat(),
            "dimensions": [d.to_dict() for d in self.dimensions],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CapabilityProfile:
        """Build a CapabilityProfile from its dict form."""
        return cls(
            model=d["model"],
            captured_at=datetime.fromisoformat(d["captured_at"]),
            dimensions=[DimensionResult.from_dict(x) for x in d.get("dimensions", [])],
        )


@dataclass(frozen=True)
class ConfigSuggestion:
    """One advisory config setting derived from the measured dimensions."""

    key: str  # e.g. "coaching.guidance"
    value: str  # e.g. "on"
    reason: str  # one line, cites the measured fact

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {"key": self.key, "value": self.value, "reason": self.reason}


@dataclass(frozen=True)
class ConfigRecommendation:
    """The advisory config block derived from a CapabilityProfile."""

    suggestions: list[ConfigSuggestion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {"suggestions": [s.to_dict() for s in self.suggestions]}


@dataclass(frozen=True)
class ProfileThresholds:
    """Tunable thresholds that turn measured facts into config advice."""

    factual_min: float = 0.50  # below → suggest template_only
    guidance_win_rate_min: float = 0.60  # at/above → suggest guidance on


# --------------------------------------------------- threshold → recommendation


def recommend(profile: CapabilityProfile, thresholds: ProfileThresholds | None = None) -> ConfigRecommendation:
    """Map measured dimensions to advisory config settings (the only place
    facts become advice; pure and isolated).

    Rules:
    - reachability ``fail`` ⇒ a single "model unusable" suggestion (and nothing
      else — downstream dimensions won't have run).
    - factual ``< factual_min`` OR ``hallucinations > 0`` ⇒
      ``coaching.template_only: true`` (else ``false``), reason cites the number.
    - guidance win-rate ``>= guidance_win_rate_min`` ⇒ ``coaching.guidance: on``
      (else ``off``), reason cites the win-rate.
    - latency ⇒ no suggestion (reported as a fact only).
    """
    th = thresholds or ProfileThresholds()
    suggestions: list[ConfigSuggestion] = []

    reach = profile.dimension("reachability")
    if reach is not None and reach.status == "fail":
        return ConfigRecommendation(
            suggestions=[
                ConfigSuggestion(
                    key="model",
                    value="(unusable)",
                    reason=f"reachability failed: {reach.notes or 'model not reachable/usable'}",
                )
            ]
        )

    factual = profile.dimension("factual")
    if factual is not None:
        score = factual.metrics.get("factual")
        halluc = factual.metrics.get("hallucinations", 0.0)
        illegal = factual.metrics.get("illegal_moves", 0.0)
        unsafe = (score is not None and score < th.factual_min) or halluc > 0 or illegal > 0
        if unsafe:
            reason = (
                f"factual={score:.2f} (< {th.factual_min:.2f})"
                if score is not None and score < th.factual_min
                else f"hallucinations={int(halluc)}, illegal_moves={int(illegal)}"
            )
            suggestions.append(
                ConfigSuggestion("coaching.template_only", "true", f"prefer deterministic templates: {reason}")
            )
        else:
            shown = f"{score:.2f}" if score is not None else "n/a"
            suggestions.append(
                ConfigSuggestion(
                    "coaching.template_only",
                    "false",
                    f"LLM is grounded (factual={shown}, 0 hallucinations/illegal)",
                )
            )

    guidance = profile.dimension("guidance")
    if guidance is not None:
        win_rate = guidance.metrics.get("on_win_rate")
        if win_rate is not None:
            if win_rate >= th.guidance_win_rate_min:
                suggestions.append(
                    ConfigSuggestion(
                        "coaching.guidance",
                        "on",
                        f"guidance helps: on win-rate {win_rate:.0%} (>= {th.guidance_win_rate_min:.0%})",
                    )
                )
            else:
                suggestions.append(
                    ConfigSuggestion(
                        "coaching.guidance",
                        "off",
                        f"guidance does not help: on win-rate {win_rate:.0%} (< {th.guidance_win_rate_min:.0%})",
                    )
                )

    return ConfigRecommendation(suggestions=suggestions)


# --------------------------------------------------------------- rendering


def render_profile(profile: CapabilityProfile) -> str:
    """Render the per-dimension facts as a human-readable report."""
    lines = [
        "=" * 70,
        f"CAPABILITY PROFILE — {profile.model}",
        f"captured: {profile.captured_at.isoformat(timespec='seconds')}",
        "=" * 70,
    ]
    for d in profile.dimensions:
        metric_str = ", ".join(f"{k}={v:g}" for k, v in d.metrics.items()) or "—"
        lat = f"{d.latency_s:.1f}s" if d.latency_s is not None else "—"
        lines.append(f"[{d.status.upper():4}] {d.name:14} | {metric_str} | latency: {lat} | n={d.samples}")
        if d.notes:
            lines.append(f"            {d.notes}")
    lines.append("=" * 70)
    return "\n".join(lines)


def render_recommendation(rec: ConfigRecommendation) -> str:
    """Render the advisory config block: a pasteable snippet + reasons."""
    if not rec.suggestions:
        return "No config recommendations (no graded dimensions ran)."
    lines = ["Recommended config (advisory — apply manually):", ""]
    for s in rec.suggestions:
        lines.append(f"  {s.key}: {s.value}")
    lines.append("")
    lines.append("Why:")
    for s in rec.suggestions:
        lines.append(f"  - {s.key} = {s.value}: {s.reason}")
    return "\n".join(lines)
