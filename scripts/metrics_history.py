"""Emit the coach metrics history: one row per stored report-card run.

Usage:
    python scripts/metrics_history.py                      # write docs/coach-metrics-history.tsv
    python scripts/metrics_history.py --svg out.svg        # also draw the trend chart
    python scripts/metrics_history.py --check <tsv>        # fail if the file is stale
    python scripts/metrics_history.py --guard              # fail if the newest version regressed

## Naming a new version's runs, which `--guard` depends on

Measure every version on ALL FIVE seeds, and name the output directories so the version and the
seed are both readable:

    output/coach_review_v53_seed7, ..._seed11, ..._seed13, ..._seed17, ..._seed23

The version comes from the first number in the name and the seed from `seed<N>`, so those five
directories become five cells of one point on the trend. A single-seed run still produces a
single-seed point, and `--guard` will then have only one cell to pair against.

`output/matrix/*` is the coverage grid — a model x opening sweep at one instant. It is NOT
versioned, so `--guard` and the trend chart both ignore it deliberately.

**Regenerates every row, every time. Never appends.** That rule is the whole design. If rows
were appended as runs happened, then the day a detector is fixed the old rows would keep the old
computation while new rows used the new one — and the line would move for reasons that have
nothing to do with the coach. It has already happened twice: `cause%` was a phrase-match until
2026-09-16 (ledger row 137) and `top-closer%` was pointing the wrong way until row 140. Both
rewrote the whole history when corrected, which is only safe because nothing is appended.

`detector` in the output is the version of THIS file's metric definitions. Bump it whenever a
metric changes meaning, so a jump in the series can be checked against a code change before it
is believed.

Reads only transcripts, which are the truth; this file is a cache.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import statistics as st
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

#: Bump when any metric's MEANING changes. 1 = cause% board-anchored (row 139) and
#: lesson-conc% composition-derived (row 140).
DETECTOR_VERSION = 1

#: Raw counts AND ratios are both emitted, on purpose.
#:
#: Counts are the auditable ground truth — "2 turns leaked a number" is checkable by opening the
#: transcript. Ratios are what can be COMPARED, because games differ in length: the five openings
#: run 23 to 51 plies, so `spoke=18` and `spoke=8` look wildly different as counts and are 41%
#: and 35% as shares. Everything charted is a ratio; the table keeps the counts.
#:
#: Denominators differ and are named in the column: `_of_plies` for how often the coach spoke at
#: all, `_of_spoken` for anything about what it said.
COLUMNS = (
    "run",
    "group",
    "detector",
    "model",
    "seed",
    "opening",
    "engine_sha",
    "plies",
    "spoke",
    "spoke_pct_of_plies",
    "clean_pct",
    "bad_turns",
    "gating",
    "cause_given_pct",
    "cause_voiced_pct",
    "mind_reading",
    "mind_reading_pct_of_spoken",
    "magnitude",
    "magnitude_pct_of_spoken",
    "words_per_turn",
    "lesson_conc_pct",
    "lesson_open",
    "lesson_open_pct_of_spoken",
)


def _hard_metrics() -> Any:
    """Import the metric definitions, so there is ONE implementation, not two."""
    path = REPO / "scripts" / "eval_hard_metrics.py"
    spec = importlib.util.spec_from_file_location("eval_hard_metrics_for_history", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["eval_hard_metrics_for_history"] = mod
    spec.loader.exec_module(mod)
    return mod


def _version_key(name: str) -> tuple[int, str]:
    m = re.search(r"(\d+)", name)
    return (int(m.group(1)) if m else 10**6, name)


#: The seed -> (opening, starting FEN) map, mirroring SEED_OPENINGS in eval_coach_review.py.
#: Duplicated rather than imported because importing that module pulls in the engine and
#: chess_coach for a report generator that needs five strings.
#:
#: Used for runs that predate the `seed` field in the environment block (anything before
#: 2026-09-18). The FEN is how the seed is RECOVERED rather than guessed: the transcript records
#: the position the game started from, and each seed has a distinct one. That matters because
#: without it the whole 48-run history has no seed, cannot be paired against a new version, and
#: `--guard` refuses every comparison.
_SEED_FALLBACK = {
    7: ("standard start", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"),
    11: ("Italian", "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 5 4"),
    13: ("Queen's Gambit", "rnbqkbnr/ppp2ppp/8/3pp3/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 3"),
    17: ("Sicilian", "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"),
    23: ("French", "rnbqkbnr/pppp1ppp/4p3/8/3PP3/8/PPP2PPP/RNBQKBNR b KQkq - 0 2"),
}
_FEN_TO_SEED = {fen: seed for seed, (_label, fen) in _SEED_FALLBACK.items()}


def _seed_from_first_position(data: dict[str, Any]) -> int | str:
    """Recover the seed from the game's opening position, or '' if it matches none.

    Evidence, not inference: the first game turn records the FEN it was played from, and the five
    seeds open from five distinct positions. Verified on v52, whose first ply is 0 from the
    standard start — seed 7, which is what the whole history used.
    """
    game = [t for t in data.get("turns", []) if isinstance(t.get("ply"), int) and t["ply"] < 1000]
    if not game:
        return ""
    return _FEN_TO_SEED.get((game[0].get("fen_before") or "").strip(), "")


#: Where runs live, and what kind each group is.
#:
#: `history` is the versioned series: one game (seed 7) per point, a time axis.
#: `matrix` is a coverage grid at ONE point in time: several openings x several models.
#: They are NOT the same shape and must not be drawn on one line — a matrix has no time axis,
#: and averaging it into the series would hide the spread that is its whole purpose.
GROUPS = (("history", "coach_review_v*"), ("matrix", "matrix/*"))


def discover(root: Path) -> list[tuple[str, Path]]:
    """`(group, transcript)` for every discoverable run, history in version order."""
    found: list[tuple[str, Path]] = []
    for group, pattern in GROUPS:
        dirs = [d for d in root.glob(pattern) if (d / "transcript.json").exists()]
        key = (lambda d: _version_key(d.name)) if group == "history" else (lambda d: (0, d.name))
        found += [(group, d / "transcript.json") for d in sorted(dirs, key=key)]
    return found


def row_for(path: Path, ehm: Any, group: str = "history") -> dict[str, Any]:
    m = ehm.measure(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    env = data.get("environment") or {}
    llm = env.get("llm") or {}
    sha = (env.get("engine") or {}).get("sha256") or ""
    conc = m.lesson_concentration

    # Seed, in order of how directly it is known: recorded in the environment, then the directory
    # name, then RECOVERED from the game's opening position. Never defaulted to 7 — that would
    # claim every unlabelled run was the standard opening.
    seed: int | str | None = env.get("seed")
    if seed is None:
        mt = re.search(r"seed(\d+)", path.parent.name)
        seed = int(mt.group(1)) if mt else _seed_from_first_position(data)
    opening = env.get("opening") or (
        _SEED_FALLBACK[seed][0] if isinstance(seed, int) and seed in _SEED_FALLBACK else ""
    )

    return {
        "run": path.parent.name.replace("coach_review_", ""),
        "group": group,
        "detector": DETECTOR_VERSION,
        # Empty rather than guessed: provenance only started being recorded 2026-09-16
        # (ledger row 138), so older runs genuinely do not know their own model.
        "model": llm.get("model") or "",
        "seed": seed,
        "opening": opening,
        "engine_sha": sha[:12],
        "plies": m.plies,
        "spoke": m.spoken,
        "spoke_pct_of_plies": f"{100.0 * m.spoken / m.plies:.0f}" if m.plies else "",
        "mind_reading_pct_of_spoken": f"{100.0 * m.mind_reading / m.spoken:.0f}" if m.spoken else "",
        "magnitude_pct_of_spoken": f"{100.0 * m.magnitude / m.spoken:.0f}" if m.spoken else "",
        "lesson_open_pct_of_spoken": f"{100.0 * m.lesson_open / m.spoken:.0f}" if m.spoken else "",
        "clean_pct": f"{m.clean_rate:.0f}",
        "bad_turns": m.turns_with_violation,
        "gating": m.gating,
        "cause_given_pct": f"{m.cause_given_rate:.0f}",
        "cause_voiced_pct": f"{m.cause_voiced_rate:.0f}",
        "mind_reading": m.mind_reading,
        "magnitude": m.magnitude,
        "words_per_turn": f"{m.words_per_turn:.0f}",
        # Empty, never 0: nothing composed means the question does not apply.
        "lesson_conc_pct": "" if conc is None else f"{conc:.0f}",
        "lesson_open": m.lesson_open,
    }


def render_tsv(rows: list[dict[str, Any]]) -> str:
    out = ["\t".join(COLUMNS)]
    out += ["\t".join(str(r[c]) for c in COLUMNS) for r in rows]
    return "\n".join(out) + "\n"


def render_legend() -> str:
    """The plain-English key, as markdown. A column name is not a description."""
    lines = [
        "# What each column means",
        "",
        "Generated by `scripts/metrics_history.py`. Data: `coach-metrics-history.tsv`.",
        "",
        "| column | the question it answers |",
        "|---|---|",
    ]
    lines += [f"| `{c}` | {q} |" for c, q in LEGEND]
    lines += [
        "",
        "## What these do NOT measure",
        "",
        "Every column above is the **absence of a defect** — nothing false, nothing invented,",
        "not repetitive, not too long. None of them can say whether the lesson was the RIGHT",
        "lesson for the position, or whether a 1200 would understand it.",
        "",
        "So this file can show that we stopped doing bad things. It cannot show that we got good.",
        "That needs the pairwise comparison against a frozen reference build, which is the other",
        "half of the tracker (see BACKLOG).",
        "",
        "## Three traps already sprung, kept here so they are not re-sprung",
        "",
        "**An empty cell is not a zero.** `lesson_conc_pct` is blank before v22 because no lesson",
        "was composed then — the question did not apply. Rendering that as 0% would read as",
        "perfect variety.",
        "",
        "**`spoke` changes what the other columns mean.** It drops from 44 to 18 at v31 when the",
        "silence gates landed. `clean_pct` rising to 100% around there is partly the coach",
        "declining to comment on turns it would have got wrong, not only getting more accurate.",
        "",
        "**Never append rows to the TSV.** It is regenerated whole, every time, from the",
        "transcripts. Appending would mix rows computed by different detector versions, and the",
        "series would move when a detector changed rather than when the coach did. That has",
        "already happened twice (`cause_given_pct`/`cause_voiced_pct`, and `lesson_conc_pct`).",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ chart

#: Panels are labelled with the QUESTION each metric answers, not the metric's name. A column
#: called "mind_reading" needs a glossary; "Does it invent the student's intent?" does not.
#:
#: `direction` is "up" when higher is better, "down" when lower is better, "flat" for context
#: metrics that are neither. It drives both the panel colour and the sign of the headline delta,
#: so a chart cannot say "improved" about a number that got worse.
#: Every panel is a RATIO, so panels stay comparable between games of different lengths. An
#: earlier version charted raw counts with a hardcoded "of 44 turns" label, which is only true
#: of the standard-start game; the five openings run 23 to 51 plies.
_PANELS = (
    ("clean_pct", "Is everything it says true?", "% of spoken turns", 100.0, "up"),
    ("cause_given_pct", "Did we compose a reason WHY?", "% of spoken turns", 100.0, "up"),
    ("cause_voiced_pct", "Did that reason reach the student?", "% of composed", 100.0, "up"),
    ("lesson_conc_pct", "Same lesson over and over?", "% on the top lesson", 40.0, "down"),
    ("lesson_open_pct_of_spoken", "Did the MODEL pick the topic?", "% of spoken turns", 100.0, "down"),
    ("mind_reading_pct_of_spoken", "Does it invent the student's intent?", "% of spoken turns", 40.0, "down"),
    ("magnitude_pct_of_spoken", "Does it leak an evaluation number?", "% of spoken, must be 0", 10.0, "down"),
    ("words_per_turn", "How long is each turn?", "words", 200.0, "flat"),
    ("spoke_pct_of_plies", "How often does it speak at all?", "% of the game's turns", 100.0, "flat"),
)


#: Column -> the question it answers, in plain English. Emitted as the legend so the TSV is
#: readable without reading this file.
LEGEND = (
    ("clean_pct", "Is everything it says true? (% of spoken turns with nothing the board contradicts)"),
    ("bad_turns", "How many turns contained something false?"),
    ("gating", "How many were false enough to block the response?"),
    ("cause_given_pct", "Did WE compose a reason why the move failed? (% of spoken turns)"),
    ("cause_voiced_pct", "Of those reasons, how many reached the student?"),
    ("mind_reading", "Does it invent the student's intent? (turns; see the _pct column to compare games)"),
    ("magnitude", "Does it leak an evaluation number? (turns; must stay 0)"),
    ("words_per_turn", "How long is each turn?"),
    ("lesson_conc_pct", "Is it teaching one lesson over and over? (% of composed lessons that are the top one)"),
    ("lesson_open", "Did the MODEL pick the topic instead of us? (turns)"),
    ("spoke", "How often did it say anything at all? (turns, of `plies`)"),
    (
        "*_pct_of_spoken",
        "The same counts as a SHARE, which is what compares across games: the five openings "
        "run 23 to 51 plies, so a raw count means different things in each",
    ),
    ("spoke_pct_of_plies", "How often it spoke, as a share of the whole game. Everything charted is a ratio"),
    ("model", "Which LLM wrote it. Blank before 2026-09-16, when provenance started being recorded"),
    ("engine_sha", "Which engine binary produced the analysis. Blank for the same reason"),
    ("detector", "Version of the metric DEFINITIONS. A jump in a series should be checked against this"),
)


_COLOUR = {"up": "#1f6f3f", "down": "#c0392b", "flat": "#555"}


def _series(rows: list[dict[str, Any]], key: str) -> list[tuple[int, float]]:
    """(version, value) for rows where the metric APPLIES. Empty cells skipped, never zeroed."""
    pts = []
    for r in rows:
        raw = r[key]
        if raw == "" or raw is None:
            continue
        pts.append((_version_key(r["run"])[0], float(raw)))
    return pts


def _agg(rows: list[dict[str, Any]], key: str) -> list[tuple[int, float, float, float]]:
    """`(version, mean, min, max)` per version, so several runs of one version become one point.

    Needed the moment a version is measured on more than one game or model. Before this, ten
    runs of v53 produced ten points at the same x and the line doubled back on itself
    vertically — not an average, just a zigzag — while the headline card picked whichever row
    happened to sort last and called it "now".

    The min/max become the spread band. With one run per version the band collapses onto the
    line, so the historical series is unchanged by this.
    """
    by_version: dict[int, list[float]] = {}
    for v, value in _series(rows, key):
        by_version.setdefault(v, []).append(value)
    return [(v, st.mean(vs), min(vs), max(vs)) for v, vs in sorted(by_version.items())]


def headline(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Latest value, and how far it has come from the WORST value ever recorded.

    Baseline is the worst observed (max for a lower-is-better metric, min for higher-is-better),
    not the first row. Two reasons, both found by sanity-checking the output:

    1. The first row is often not a comparable baseline. `lesson_open` reads 0 at v2 because no
       closing instruction existed at all, then 44 once we started asking openly, then 2 today.
       First-to-last says "0 to 2, worse". Worst-to-last says "down from 44", which is the truth.
    2. "How far have we come" is the question a dashboard is for, and the worst point answers it
       without cherry-picking — it is the whole recorded range, not a flattering slice.

    `better` is None when nothing moved. A zero delta was previously labelled a regression,
    because `delta < 0` is false for it.
    """
    cards = []
    for key, label, unit, _ymax, direction in _PANELS:
        agg = _agg(rows, key)
        if not agg:
            continue
        # One value per VERSION, so "now" is the latest version's mean across its games and
        # models rather than whichever run happened to sort last.
        pts = [(v, mean) for v, mean, _lo, _hi in agg]
        v_last, last = pts[-1]
        spread = next((hi - lo for v, _m, lo, hi in agg if v == v_last), 0.0)

        # Best and worst ever recorded, by this metric's own direction.
        if direction == "down":
            v_best, best = min(pts, key=lambda p: p[1])
            v_worst, worst = max(pts, key=lambda p: p[1])
        else:
            v_best, best = max(pts, key=lambda p: p[1])
            v_worst, worst = min(pts, key=lambda p: p[1])

        # State, not a delta. An earlier version compared the latest value against the worst
        # ever, which reads "flat throughout" when the latest value IS the worst — it hid a
        # decline, and a metric reporting the flattering reading while blind is the failure
        # this file keeps recording.
        if direction == "flat" or len(pts) < 2:
            state, word, v_base, base = "context", "was", pts[0][0], pts[0][1]
        elif last == best and best != worst:
            state, word, v_base, base = "best", "worst was", v_worst, worst
        elif last == worst and best != worst:
            state, word, v_base, base = "worst", "best was", v_best, best
        elif best == worst:
            state, word, v_base, base = "unchanged", "flat at", v_best, best
        else:
            state, word, v_base, base = "middling", "worst was", v_worst, worst
        delta = last - base
        better = {"best": True, "worst": False, "middling": True, "unchanged": None, "context": None}[state]
        cards.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "now": last,
                "base": base,
                "base_word": word,
                "from_run": f"v{v_base}",
                "to_run": f"v{v_last}",
                "delta": delta,
                "spread": spread,
                "state": state,
                "best": best,
                "worst": worst,
                "runs_in_latest": sum(1 for v, _x in _series(rows, key) if v == v_last),
                "better": None if direction == "flat" else better,
                "direction": direction,
            }
        )
    return cards


def render_svg(rows: list[dict[str, Any]], cols: int = 3, title: bool = True) -> str:
    """Trend chart. HISTORY rows only — this refuses anything else, on purpose.

    The x axis is the version number, parsed from the run name. A matrix run is named like
    `gemma12_seed11`, and `_version_key` happily returns 12 for it, so passing a mixed list
    produced a chart with 20 spurious points scattered mid-axis and a heading that read
    "v2 to v52 (68 runs)". Nothing failed; the picture was just wrong.

    A wrong chart is worse than no chart, so this raises rather than filtering silently.
    """
    wrong = sorted({r["group"] for r in rows if r.get("group") != "history"})
    if wrong:
        raise ValueError(f"render_svg takes history rows only; got groups {wrong}. Filter before calling.")
    # `top` must leave room for each panel's label + hint, drawn at y0-16 and y0-3, clear of
    # the chart title at y=26.
    pw, ph, gap, left = 300, 130, 52, 58
    top = 64 if title else 28
    nrows = (len(_PANELS) + cols - 1) // cols
    xs = [_version_key(r["run"])[0] for r in rows]
    x_lo, x_hi = min(xs), max(xs)
    width = left + cols * (pw + gap)
    height = top + nrows * (ph + gap) + 30

    def px(v: float, x0: int) -> float:
        return x0 + (v - x_lo) / max(1, x_hi - x_lo) * pw

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui,sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
    ]
    if title:
        parts.append(
            f'<text x="{left}" y="26" font-size="17" font-weight="600">chess-coach metrics, '
            f"v{x_lo} to v{x_hi} ({len(rows)} report-card runs)</text>"
        )
    for i, (key, label, unit, ymax, direction) in enumerate(_PANELS):
        x0 = left + (i % cols) * (pw + gap)
        y0 = top + (i // cols) * (ph + gap)
        colour = _COLOUR[direction]
        hint = {"up": "higher better", "down": "LOWER better", "flat": "context"}[direction]
        parts.append(f'<rect x="{x0}" y="{y0}" width="{pw}" height="{ph}" fill="#fafafa" stroke="#ddd"/>')
        # Column name first, then the question. The name is what the TSV calls it, so a panel
        # can be traced back to a column without a glossary; the question is what it means.
        parts.append(
            f'<text x="{x0}" y="{y0 - 16}" font-size="12">'
            f'<tspan font-family="ui-monospace,Consolas,monospace" fill="#8a6d3b">{key}</tspan>'
            f'<tspan font-weight="600" fill="#1a1a1a"> &#183; {label}</tspan></text>'
        )
        parts.append(f'<text x="{x0}" y="{y0 - 3}" font-size="10" fill="{colour}">{unit} &#183; {hint}</text>')
        for frac in (0.0, 0.5, 1.0):
            yy = y0 + ph - frac * ph
            parts.append(f'<line x1="{x0}" y1="{yy:.1f}" x2="{x0 + pw}" y2="{yy:.1f}" stroke="#e8e8e8"/>')
            parts.append(
                f'<text x="{x0 - 6}" y="{yy + 3:.1f}" font-size="9" fill="#888" '
                f'text-anchor="end">{ymax * frac:.0f}</text>'
            )

        # One point per VERSION: the mean over that version's runs, with a band between its
        # min and max. Several runs of one version used to produce several points at the same
        # x, so the line doubled back on itself vertically.
        #
        # Versions absent from the aggregate are versions where the metric did not apply, and
        # the line BREAKS there rather than being drawn at zero.
        def y_of(value: float) -> float:
            return y0 + ph - min(value, ymax) / ymax * ph

        agg = _agg(rows, key)
        present = {v for v, *_ in agg}
        all_versions = [_version_key(r["run"])[0] for r in rows]
        seg: list[tuple[float, float, float, float]] = []
        segments: list[list[tuple[float, float, float, float]]] = []
        for v in sorted(set(all_versions)):
            hit = next((a for a in agg if a[0] == v), None)
            if hit is None or v not in present:
                if len(seg) > 1:
                    segments.append(seg)
                seg = []
                continue
            _v, mean, lo, hi = hit
            seg.append((px(v, x0), y_of(mean), y_of(lo), y_of(hi)))
        if len(seg) > 1:
            segments.append(seg)

        for sgm in segments:
            # Band first, so the mean line draws on top of it.
            if any(abs(lo - hi) > 0.5 for _x, _m, lo, hi in sgm):
                top_edge = " ".join(f"{x:.1f},{hi:.1f}" for x, _m, _lo, hi in sgm)
                bot_edge = " ".join(f"{x:.1f},{lo:.1f}" for x, _m, lo, _hi in reversed(sgm))
                parts.append(
                    f'<polygon points="{top_edge} {bot_edge}" fill="{colour}" fill-opacity="0.16" stroke="none"/>'
                )
            line = " ".join(f"{x:.1f},{m:.1f}" for x, m, _lo, _hi in sgm)
            parts.append(f'<polyline points="{line}" fill="none" stroke="{colour}" stroke-width="2"/>')
        for lab in (x_lo, 31, x_hi):
            parts.append(
                f'<text x="{px(lab, x0):.1f}" y="{y0 + ph + 13}" font-size="9" fill="#888" '
                f'text-anchor="middle">v{lab}</text>'
            )
    # How to READ the chart, only. No commentary about particular runs: an annotation like
    # "v31 is where the silence gates landed" is ledger content, and hardcoding it here means
    # the chart carries a story that goes stale while the data keeps updating.
    parts.append(
        f'<text x="{left}" y="{height - 8}" font-size="10" fill="#666">'
        "A gap in a line means the metric did not apply to those runs &#8212; not zero.</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts)


# ------------------------------------------------------------------ dashboard

_CSS = """
:root { --ink:#1a1a1a; --dim:#666; --line:#e2e2e2; --good:#1f6f3f; --bad:#c0392b; }
* { box-sizing: border-box; }
body { margin:0; padding:32px; font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;
       color:var(--ink); background:#fff; max-width:1180px; }
h1 { font-size:24px; margin:0 0 4px; }
h2 { font-size:17px; margin:38px 0 12px; padding-bottom:6px; border-bottom:1px solid var(--line); }
.sub { color:var(--dim); margin:0 0 26px; font-size:13px; }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:12px; }
.card { border:1px solid var(--line); border-radius:6px; padding:12px 14px; }
.card .q { font-size:12px; color:var(--dim); min-height:50px; }
.card .q code { background:#fdf6e3; color:#8a6d3b; font-size:11px; }
.card .now { font-size:27px; font-weight:600; line-height:1.1; margin-top:4px; }
.card .un { font-size:11px; color:var(--dim); }
.card .d { font-size:12px; margin-top:6px; }
.up { color:var(--good); } .down { color:var(--bad); } .flat { color:var(--dim); }
table { border-collapse:collapse; font-size:12px; width:100%; }
th,td { padding:4px 8px; border-bottom:1px solid var(--line); text-align:right;
        font-variant-numeric:tabular-nums; }
th:first-child, td:first-child { text-align:left; font-weight:600; }
thead th { font-size:11px; color:var(--dim); font-weight:600; }
tbody tr:hover { background:#fafafa; }
.warn { border-left:3px solid #d9a600; background:#fffdf5; padding:12px 16px; margin:14px 0;
        font-size:13px; }
code { background:#f4f4f4; padding:1px 4px; border-radius:3px; font-size:12px; }
"""

_TABLE_COLS = (
    ("run", "run"),
    ("model", "model"),
    ("spoke", "spoke"),
    ("clean_pct", "true%"),
    ("bad_turns", "bad"),
    ("gating", "gated"),
    ("cause_given_pct", "cause giv%"),
    ("cause_voiced_pct", "cause voi%"),
    ("mind_reading", "mind-rd"),
    ("magnitude", "magn"),
    ("lesson_conc_pct", "lesson conc%"),
    ("lesson_open", "model picked"),
    ("words_per_turn", "words"),
)


def render_matrix(rows: list[dict[str, Any]]) -> str:
    """Coverage grid at one point in time: what moves a metric, the coach or the conditions?

    For each metric, the largest spread across OPENINGS holding the model fixed, and across
    MODELS holding the opening fixed. The build is identical in every cell, so anything that
    moves is not the coach.

    This is the table that says whether a number is worth reading. A metric whose opening-range
    is 27 points cannot be compared between two builds measured on different openings.
    """
    if not rows:
        return "<p class='sub'>No matrix runs found.</p>"

    models = sorted({r["model"] for r in rows if r["model"]})
    openings = sorted({(r["seed"], r["opening"]) for r in rows if r["opening"]})

    body = []
    for key, label, _unit, _ymax, _direction in _PANELS:
        by_model: dict[str, list[float]] = {}
        by_seed: dict[Any, list[float]] = {}
        for r in rows:
            raw = r[key]
            if raw == "" or raw is None:
                continue
            by_model.setdefault(r["model"], []).append(float(raw))
            by_seed.setdefault(r["seed"], []).append(float(raw))
        if not by_model:
            continue
        # Spread caused by the OPENING = range within one model, worst case over models.
        open_rng = max((max(v) - min(v)) for v in by_model.values())
        # Spread caused by the MODEL = range within one opening, worst case over openings.
        model_rng = max((max(v) - min(v)) for v in by_seed.values())
        allv = [x for v in by_model.values() for x in v]
        verdict = (
            "stable in every cell"
            if open_rng == 0 and model_rng == 0
            else "the OPENING"
            if open_rng > model_rng
            else "the MODEL"
            if model_rng > open_rng
            else "opening and model alike"
        )
        cls = "up" if max(open_rng, model_rng) == 0 else "down" if max(open_rng, model_rng) >= 10 else "flat"
        body.append(
            f"<tr><td><code>{key}</code><br><span style='font-weight:400;color:#666'>{label}</span></td>"
            f"<td>{min(allv):.0f}&ndash;{max(allv):.0f}</td><td>{open_rng:.0f}</td>"
            f"<td>{model_rng:.0f}</td><td class='{cls}' style='text-align:left'>{verdict}</td></tr>"
        )

    grid = ", ".join(f"{o} (seed {s})" for s, o in openings)
    model_list = ", ".join(f"<code>{m}</code>" for m in models)
    return f"""<p class="sub">{len(rows)} runs on one identical build:
{len(models)} models &times; {len(openings)} openings. Models: {model_list}.
Openings: {grid}.</p>
<table><thead><tr><th>metric</th><th>observed</th><th>moved by opening</th>
<th>moved by model</th><th style="text-align:left">dominated by</th></tr></thead>
<tbody>{"".join(body)}</tbody></table>
<p class="sub">The build does not change between these cells, so any spread here is the
conditions, not the coaching. A metric with a large opening-range cannot be compared across
builds measured on different openings.</p>
"""


def render_dashboard(rows: list[dict[str, Any]]) -> str:
    """One self-contained HTML file: headline cards, the charts, the legend, the data.

    No JavaScript, no CDN, no build step. It opens from disk on any of the three machines and
    keeps working offline, which a charting library would not.
    """
    # The two groups are different shapes and are presented separately. `history` is a time
    # axis; `matrix` is a coverage grid at one instant. Mixing them would put a spread on a
    # trend line and read as movement.
    hist = [r for r in rows if r["group"] == "history"]
    mat = [r for r in rows if r["group"] == "matrix"]
    if not hist:
        hist = rows

    cards = []
    for c in headline(hist):
        cls = "flat" if c["better"] is None else ("up" if c["better"] else "down")
        prefix = {
            "best": "&#9650; best so far",
            "worst": "&#9660; WORST so far",
            "middling": "&#9650;",
            "unchanged": "unchanged",
            "context": "",
        }[c["state"]]
        note = prefix if c["state"] == "unchanged" else f"{prefix} &middot; {c['base_word']} {c['base']:.0f}"
        if c["state"] != "unchanged":
            note += f" at {c['from_run']}"
        # Spread across the latest version's runs, shown only when it has more than one.
        if c["runs_in_latest"] > 1:
            note += f'<br><span class="flat">&plusmn;{c["spread"] / 2:.0f} over {c["runs_in_latest"]} runs</span>'
        cards.append(
            f'<div class="card"><div class="q"><code>{c["key"]}</code><br>{c["label"]}</div>'
            f'<div class="now">{c["now"]:.0f}<span class="un"> {c["unit"]}</span></div>'
            f'<div class="d {cls}">{note}</div></div>'
        )

    head = "".join(f"<th>{lab}</th>" for _k, lab in _TABLE_COLS)
    body = []
    for r in reversed(rows):  # newest first
        tds = "".join(f"<td>{r[k] if r[k] != '' else '&ndash;'}</td>" for k, _lab in _TABLE_COLS)
        body.append(f"<tr>{tds}</tr>")

    legend = "".join(f"<tr><td><code>{k}</code></td><td style='text-align:left'>{q}</td></tr>" for k, q in LEGEND)
    runs = f"{hist[0]['run']} to {hist[-1]['run']}"

    # Coverage is computed, not asserted. A dashboard that silently rests on one game and an
    # unknown model is worse than one that says so: the numbers look like a trend either way.
    openings = sorted({r["opening"] for r in hist if r["opening"]})
    unknown = sum(1 for r in hist if not r["model"])
    scope = []
    if len(openings) <= 1:
        scope.append(
            f"<strong>Every point in the trend is one game</strong>"
            f"{f' ({openings[0]})' if openings else ''}. Not an average over games."
        )
    else:
        scope.append(f"Trend covers {len(openings)} openings: {', '.join(openings)}.")
    if unknown:
        scope.append(
            f"<strong>{unknown} of {len(hist)} trend runs do not know which model wrote them.</strong> "
            "Run provenance started on 2026-09-16, and the configured model changed mid-project "
            "with nothing marking when &mdash; so a step in a trend line could be a model change "
            "rather than a coaching change."
        )
    if mat:
        scope.append(
            f"The coverage grid below <em>does</em> span models and openings "
            f"({len(mat)} runs), but at a single point in time."
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>chess-coach metrics dashboard</title><style>{_CSS}</style></head><body>
<h1>chess-coach coaching metrics</h1>
<p class="sub">{len(rows)} report-card runs, {runs} &middot; detector v{DETECTOR_VERSION} &middot;
regenerated by <code>scripts/metrics_history.py</code> from stored transcripts</p>

<h2>Where we are now</h2>
<div class="cards">{"".join(cards)}</div>

<div class="warn" style="border-left-color:#c0392b;background:#fff6f5">
<strong>What this does NOT yet cover.</strong><br>{"<br>".join(scope)}
<br><br>So the trend lines answer &ldquo;did this build change&rdquo; only for one game on an
unidentified model. The coverage grid answers &ldquo;is this metric worth reading at all&rdquo;.
Neither answers both at once yet.</div>

<div class="warn"><strong>Read <code>spoke</code> alongside the rest.</strong> Every
percentage is a share of the turns the coach chose to speak on, so a rise can mean better
coaching or fewer turns attempted. The two are not separable from this page.</div>

<h2>Over time</h2>
{render_svg(hist, cols=3, title=False)}
<p class="sub">A gap in a line means the metric did not apply to those runs &mdash; not zero.</p>

<h2>What actually moves each metric</h2>
{render_matrix(mat)}

<h2>What each column means</h2>
<p class="sub">Every column below is the absence of a defect. None of them can say whether the
lesson was the RIGHT lesson for the position, or whether a 1200 would understand it.</p>
<table><thead><tr><th>column</th><th style="text-align:left">the question it answers</th></tr>
</thead><tbody>{legend}</tbody></table>

<h2>Every run</h2>
<table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>
<p class="sub">Newest first. <code>model</code> and <code>engine_sha</code> are blank before
2026-09-16, when run provenance started being recorded &mdash; those runs genuinely do not know
what produced them.</p>
</body></html>
"""


#: How much a metric may move the wrong way before `--guard` calls it a regression, in
#: percentage points.
#:
#: Three, because every metric is now a share of the turns the coach spoke on, and a typical
#: game has 18 of those — so one turn is 5.6 points and this sits just under it. Anything
#: smaller than a single turn is not a finding.
#:
#: Deliberately NOT the cross-game noise floor measured in the matrix, which runs to 27 points
#: for `cause_given_pct` and 50 for `cause_voiced_pct`. That spread is caused by playing a
#: DIFFERENT game, and the guard never compares different games: it pairs cells with the same
#: seed and model, where the only thing that changed is the build. Using the cross-game floor
#: here would set the bar so high that nothing could ever trip it.
GUARD_TOLERANCE_PP = 3.0


def guard(rows: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """Did the newest version regress against the one before it? `(exit_code, lines)`.

    Compares PAIRED cells — same seed, same model — so game and model variation cancels out
    instead of being averaged over. The report card runs the coach at temperature 0, so a paired
    cell differs only when the build differs, which is what makes a three-point tolerance
    defensible rather than invented.

    Refuses to compare when the two versions share no cell, rather than comparing a Sicilian run
    against a French one and reporting the difference as a regression.
    """
    out: list[str] = []
    versions = sorted({_version_key(r["run"])[0] for r in rows})
    if len(versions) < 2:
        return 0, ["guard: need at least two versions; nothing to compare"]
    prev_v, last_v = versions[-2], versions[-1]

    # Pair on seed AND model when both versions know their model. When either side does not —
    # every run before 2026-09-16 — pair on the seed alone and say the model is unverified.
    # Refusing outright would make the guard useless against the entire recorded history, and
    # the seed is the variable that actually moves the metrics: 27 points for
    # `cause_given_pct` across openings, against 0 for the model on that same metric.
    def known(v: int) -> bool:
        return all(r["model"] for r in rows if _version_key(r["run"])[0] == v)

    paired_on_model = known(prev_v) and known(last_v)

    def cells(v: int) -> dict[Any, dict[str, Any]]:
        return {
            ((r["seed"], r["model"]) if paired_on_model else r["seed"]): r
            for r in rows
            if _version_key(r["run"])[0] == v
        }

    before, after = cells(prev_v), cells(last_v)
    shared = sorted(set(before) & set(after), key=str)
    how = "same seed AND model" if paired_on_model else "same seed; MODEL UNVERIFIED on one side"
    out.append(f"guard: v{prev_v} -> v{last_v}, {len(shared)} paired cell(s) ({how})")
    if not shared:
        out.append(
            f"  REFUSING to compare: v{prev_v} and v{last_v} share no cell. "
            "Comparing different games would report game variation as a regression."
        )
        return 1, out
    if not paired_on_model:
        out.append(
            "  NOTE: at least one side does not record its model, so a difference below could be "
            "a model change. Model affects words_per_turn and cause_voiced_pct; it does not "
            "affect cause_given_pct, lesson_conc_pct or spoke at all (measured)."
        )

    failures = 0
    for key, label, _unit, _ymax, direction in _PANELS:
        if direction == "flat":
            continue
        deltas = []
        for cell in shared:
            b, aft = before[cell][key], after[cell][key]
            if b == "" or aft == "":
                continue
            deltas.append(float(aft) - float(b))
        if not deltas:
            continue
        worst = max(deltas) if direction == "down" else min(deltas)
        bad = worst > GUARD_TOLERANCE_PP if direction == "down" else worst < -GUARD_TOLERANCE_PP
        mean_d = st.mean(deltas)
        mark = "FAIL" if bad else "ok  "
        out.append(f"  {mark} {key:<28} mean {mean_d:+6.1f}pp  worst cell {worst:+6.1f}pp   {label}")
        failures += bool(bad)

    out.append(
        f"guard: {failures} regression(s) beyond {GUARD_TOLERANCE_PP:.0f}pp"
        + ("" if failures else " — nothing got worse")
    )
    if failures:
        # Do NOT let the next reader do what I did on 2026-09-21: dismiss a real 8-point drop as
        # noise because another measurement said the metric was jumpy. That other measurement was
        # the cross-OPENING spread, which says nothing about a paired cell. The only way to know
        # whether a flagged difference is noise is to check whether the PROMPT changed on the turns
        # that moved, so the guard now names the command that answers it.
        for cell in shared[:3]:
            a_run, b_run = before[cell]["run"], after[cell]["run"]
            out.append(
                f"  attribute it: python scripts/eval_repeat_budget.py --compare "
                f"output/coach_review_{a_run} output/coach_review_{b_run}"
            )
        out.append(
            "  A difference is only noise if the prompt was IDENTICAL on the turns that moved. "
            "If the prompt changed, the difference is your code."
        )
    return (1 if failures else 0), out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default=str(REPO / "docs" / "coach-metrics-history.tsv"))
    p.add_argument("--svg")
    p.add_argument("--check", help="compare against this file and fail if stale")
    p.add_argument("--guard", action="store_true", help="fail if the newest version regressed")
    p.add_argument("--transcripts", default=str(REPO / "output"))
    a = p.parse_args(argv[1:])

    ehm = _hard_metrics()
    found = discover(Path(a.transcripts))
    if not found:
        print(f"no transcripts under {a.transcripts}")
        return 1
    rows = [row_for(q, ehm, group) for group, q in found]
    tsv = render_tsv(rows)

    if a.guard:
        code, lines = guard([r for r in rows if r["group"] == "history"])
        print("\n".join(lines))
        return code

    if a.check:
        have = Path(a.check).read_text(encoding="utf-8") if Path(a.check).exists() else ""
        if have != tsv:
            print(f"STALE: {a.check} does not match a fresh computation over {len(rows)} runs")
            return 1
        print(f"up to date: {len(rows)} runs")
        return 0

    Path(a.out).write_text(tsv, encoding="utf-8")
    print(f"wrote {a.out} ({len(rows)} runs, detector v{DETECTOR_VERSION})")
    legend = Path(a.out).with_name("coach-metrics.md")
    legend.write_text(render_legend(), encoding="utf-8")
    print(f"wrote {legend}")
    dash = Path(a.out).with_name("coach-metrics-dashboard.html")
    dash.write_text(render_dashboard(rows), encoding="utf-8")
    print(f"wrote {dash}")
    if a.svg:
        hist = [r for r in rows if r["group"] == "history"]
        Path(a.svg).write_text(render_svg(hist), encoding="utf-8")
        print(f"wrote {a.svg} ({len(hist)} history runs; {len(rows) - len(hist)} matrix runs excluded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
