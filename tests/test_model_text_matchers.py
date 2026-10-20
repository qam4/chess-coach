"""No regex, phrase list or keyword match over model-written prose (owner's ruling, 2026-10-14).

Three written rules already said a measure must never match the model's phrasing
(`.kiro/steering/judge-reporting.md`, step 4 of `.kiro/steering/work-loop.md`, and the global
work loop), and they were bypassed anyway. On 2026-10-13 a checker matching "is still available"
after the played move was added to `verify.py`, and the scratch measurements of the same item used
the same kind of match. Each time it was an agent that had read the rule and argued its own case
was an exception. A rule that depends on the reader's judgement failed at exactly that point, so
this one asks for none.

It freezes every string-matching construct in the files that handle model text: each regex
pattern, each string literal tested with `in`, each `startswith`/`endswith` literal, each tuple,
list or set of string literals, and each use of a module-level pattern constant. They are counted
with their multiplicity, so reusing an existing phrase in a new place fails as surely as writing a
new one. The ones listed in `tests/model_text_matchers.txt` predate the ruling. They are recorded,
not endorsed: do not extend them; whether to replace them is the owner's decision.

A file is in scope when its source mentions any of `MARKERS`, so a NEW script that reads the
coach's text is covered without anyone remembering to add it.

**If this test fails, do not regenerate the list to make it pass. Stop and ask the owner.** After an
approved change, regenerate with ``python tests/test_model_text_matchers.py --write`` and say in the
commit that the list changed.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FROZEN = REPO / "tests" / "model_text_matchers.txt"
ROOTS = ("src", "scripts")

#: A file that contains any of these handles text a model wrote: a provider producing it, a caller
#: receiving it from a provider or from the Coach, the fidelity gate's input, the coach's reply as
#: stored in a transcript, or a judge's reply. Deliberately wide. A file swept in that only matches
#: strings of its own costs one question to the owner; a file left out is unguarded. The first
#: version missed `eval_coaching.py` and `eval_models.py`, which keyword-matched the model's reply
#: (both removed in B-021, 2026-10-19).
MARKERS = (
    "def generate(",
    ".generate(",
    ".explain(",
    ".evaluate_move(",
    ".play_move(",
    ".explain_engine_move(",
    "coach_feedback",
    "check_text_fidelity",
    "check_coaching_fidelity",
    "generate_verified",
    "parse_verdict",
    "parse_pairwise",
    "_extract_json_object",
)

_RE_FUNCS = frozenset({"compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "subn", "split"})
#: A module-level constant: `_SAN_RE`, `MIND_READING_RE`. Calls on these are uses of a frozen pattern.
_CONSTANT_NAME = re.compile(r"^_?[A-Z][A-Z0-9_]*$")


def _one_line(node: ast.AST) -> str:
    return " ".join(ast.unparse(node).split())


def _is_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def matchers_in(source: str) -> list[tuple[str, str]]:
    """``(kind, text)`` for every string-matching construct in ``source``, with repeats."""
    out: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            receiver = func.value
            if isinstance(receiver, ast.Name) and receiver.id == "re" and func.attr in _RE_FUNCS and node.args:
                out.append(("regex", _one_line(node.args[0])))
            elif isinstance(receiver, ast.Name) and _CONSTANT_NAME.match(receiver.id) and func.attr in _RE_FUNCS:
                out.append(("pattern-use", f"{receiver.id}.{func.attr}"))
            elif func.attr in ("startswith", "endswith") and node.args and _is_str(node.args[0]):
                out.append(("affix", f"{func.attr}({_one_line(node.args[0])})"))
        elif isinstance(node, ast.Compare):
            if _is_str(node.left) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
                out.append(("in", _one_line(node.left)))
        elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            if len(node.elts) >= 2 and all(_is_str(e) for e in node.elts):
                out.append(("strings", _one_line(node)))
    return out


def in_scope() -> list[Path]:
    """Files under `ROOTS` that handle model text. This test file is excluded: it names the markers."""
    files = []
    for root in ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if any(marker in text for marker in MARKERS):
                files.append(path)
    return files


def current() -> list[str]:
    lines = []
    for path in in_scope():
        rel = path.relative_to(REPO).as_posix()
        for kind, text in matchers_in(path.read_text(encoding="utf-8")):
            lines.append(f"{rel}\t{kind}\t{text}")
    return sorted(lines)


def frozen() -> list[str]:
    return sorted(ln for ln in FROZEN.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#"))


_HEADER = (
    "# Every string-matching construct in code that handles model text, frozen 2026-10-14.\n"
    "# Generated by tests/test_model_text_matchers.py. These PREDATE the owner's ruling against\n"
    "# regex on model output: they are recorded, not endorsed. Changing this file needs the owner's\n"
    "# approval, and the commit that changes it says so.\n"
)


def test_no_new_string_matching_on_model_text() -> None:
    have, want = Counter(current()), Counter(frozen())
    added = sorted((have - want).elements())
    removed = sorted((want - have).elements())
    assert not added and not removed, (
        "String matching changed in code that handles model text. The owner's ruling (2026-10-14): "
        "no regex, phrase list or keyword match over model-written prose. Do NOT regenerate the "
        "frozen list to make this pass — stop and ask the owner.\n"
        + "".join(f"  added:   {a}\n" for a in added)
        + "".join(f"  removed: {r}\n" for r in removed)
    )


def test_the_files_the_audit_found_are_in_scope() -> None:
    """If the markers drift, these must not silently fall out of scope."""
    scope = {p.relative_to(REPO).as_posix() for p in in_scope()}
    for path in (
        "src/chess_coach/verify.py",
        "src/chess_coach/eval/coach_review.py",
        "src/chess_coach/eval/objective.py",
        "src/chess_coach/eval/judge.py",
        "scripts/eval_hard_metrics.py",
        "scripts/eval_run.py",
    ):
        assert path in scope, f"{path} handles model text and is not being guarded"


def test_it_would_have_caught_the_check_it_exists_for() -> None:
    """The removed `played_offered` check, as it was written. Its regex must register."""
    source = (
        "_OFFERED_AS_AVAILABLE_RE = re.compile(r'[+#]?,?\\s+(?:is|was)\\s+(?:still\\s+)?available\\b', re.IGNORECASE)\n"
        "def f(text):\n"
        "    for m in _SAN_RE.finditer(text):\n"
        "        if _OFFERED_AS_AVAILABLE_RE.match(text, m.end()):\n"
        "            return True\n"
    )
    kinds = Counter(kind for kind, _text in matchers_in(source))
    assert kinds["regex"] == 1
    assert kinds["pattern-use"] == 2


def test_each_kind_of_matching_registers() -> None:
    source = (
        "def f(window, text):\n"
        "    if 'available' in window:\n"
        "        return 1\n"
        "    if text.endswith('...'):\n"
        "        return 2\n"
        "    return any(cue in window for cue in ('could have', 'should have'))\n"
    )
    assert sorted(kind for kind, _text in matchers_in(source)) == ["affix", "in", "strings"]


def test_reusing_an_existing_phrase_in_a_new_place_counts() -> None:
    """Multiplicity is the point: a second `'opponent' in window` is a new check."""
    once = matchers_in("def f(w):\n    return 'opponent' in w\n")
    twice = matchers_in("def f(w, x):\n    return 'opponent' in w or 'opponent' in x\n")
    assert len(twice) == 2 * len(once) == 2


def test_ordinary_code_does_not_register() -> None:
    """A lone string, a variable `in` test and a method on a non-constant are not matching."""
    source = "def f(token, ch, text):\n    name = 'pawn'\n    return ch in token or text.split()\n"
    assert matchers_in(source) == []


if __name__ == "__main__" and "--write" in sys.argv:
    FROZEN.write_text(_HEADER + "\n".join(current()) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {FROZEN.relative_to(REPO)}: {len(current())} entries from {len(in_scope())} files")
