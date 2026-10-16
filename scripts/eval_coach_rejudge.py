"""Re-judge a SAVED report-card transcript — no coach, no engine, no tunnel.

Why this exists: the coach's output and the judge's ASK are two independent
variables, and we kept changing them together. Re-judging a byte-identical
transcript isolates the ask. That experiment has already paid for itself once —
re-judging v21 with a corrected stats block turned its headline weakness into its
second strength, proving the complaint was about our labelling and not the coach.

Use it to compare rubric versions on the same game:

    python scripts/eval_coach_rejudge.py \
        --transcript output/coach_review_v26/transcript.json \
        --rubric v2 --out output/coach_review_v26_rubric_v2

Or both asks back to back:

    python scripts/eval_coach_rejudge.py \
        --transcript output/coach_review_v26/transcript.json --rubric v1,v2 \
        --out output/rejudge_v26

The judge defaults to claude-opus-5 and the command is derived from the model, so
the two cannot silently disagree.

B-021: the same transcript can instead be read for its BOARD CLAIMS. The judge writes every claim
each draft makes as JSON and python-chess checks them (`chess_coach.eval.claims`):

    python scripts/eval_coach_rejudge.py --claims --runs 2 \
        --transcript output/coach_review_v62_seed7/transcript.json --out output/b021_claims/v62_seed7

A reading written by someone else (the agent) answering the same `claims_prompt.txt` is scored the
same way with `--claims-reply FILE --reader agent`. Readings are compared, and graded against
today's gate, with `--claims-compare DIR [DIR ...] --readers judge_r1,judge_r2,agent`.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chess_coach.eval import claims as cl  # noqa: E402
from chess_coach.eval.coach_review import (  # noqa: E402
    RUBRIC_VERSIONS,
    ReviewStats,
    ReviewTurn,
    build_coach_review_prompt,
    resolve_judge_agent,
)
from chess_coach.llm import create_provider  # noqa: E402
from chess_coach.verify import check_text_fidelity, gating_violations  # noqa: E402


def _judge(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    # Via --agent, not --model: `--model` is a no-op in kiro-cli 2.22.1 and every run recorded as
    # claude-opus-5 was served by the `auto` default. Third caller of this pattern; the other two
    # were fixed on 2026-09-22 and this one was missed.
    if args.judge_command is None:
        resolved = resolve_judge_agent(args.judge_agent, args.judge_model)
        print(f"judge: agent {args.judge_agent} pins {resolved}")
    command = args.judge_command or f"kiro-cli chat --no-interactive --agent {args.judge_agent}"
    return create_provider(
        "cli",
        model=args.judge_model,
        base_url=args.judge_base_url,
        api_key="",
        command=shlex.split(command),
        timeout=1800.0,
    )


def _write_scored(out_dir: Path, reader: str, drafts: list[cl.Draft], reply: str, args: argparse.Namespace) -> None:
    raw = out_dir / f"claims_reply_{reader}.txt"
    if not raw.exists() or raw.read_text(encoding="utf-8") != reply:
        raw.write_text(reply, encoding="utf-8")
    scored = cl.score_reading(drafts, cl.parse_claims_reply(reply))
    verdicts = [s["verdict"] for s in scored.values()]
    summary = {v: verdicts.count(v) for v in (cl.FALSE, cl.CLEAN, cl.UNRESOLVED, cl.MISSING)}
    record = {"reader": reader, "transcript": args.transcript, "summary": summary, "drafts": scored}
    (out_dir / f"claims_{reader}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"  {reader}: {len(drafts)} drafts {summary}")


def _claims(args: argparse.Namespace) -> None:
    """Read every distinct draft in the transcript for its board claims, and score them."""
    data = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    drafts = cl.drafts_of(data, seed=int(data["environment"]["seed"]))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.claims_reply:
        # Scoring a reply already written: `claims_prompt.txt` stays as the prompt that reader saw.
        print(f"{len(drafts)} distinct drafts from {args.transcript}, scoring {args.claims_reply}")
        _write_scored(out_dir, args.reader, drafts, Path(args.claims_reply).read_text(encoding="utf-8"), args)
        return
    prompt = cl.build_claims_prompt(drafts)
    (out_dir / "claims_prompt.txt").write_text(prompt, encoding="utf-8")
    print(f"{len(drafts)} distinct drafts from {args.transcript} ({len(prompt)} chars)")
    judge = _judge(args)
    for run in range(1, args.runs + 1):
        print(f"progress={run}/{args.runs} judge reading run {run}")
        t0 = time.perf_counter()
        reply = ""
        for _attempt in range(2):  # one retry on an unparseable reply, as `judge_response` does
            reply = judge.generate(prompt)
            try:
                cl.parse_claims_reply(reply)
                break
            except cl.ClaimsParseError as e:
                print(f"  run {run}: unparseable reply, retrying ({e})")
        print(f"  run {run} done in {time.perf_counter() - t0:.0f}s ({len(reply)} chars)")
        _write_scored(out_dir, f"judge_r{run}", drafts, reply, args)
    print(f"progress={args.runs}/{args.runs} complete")


def _claims_local(args: argparse.Namespace) -> None:
    """A LOCAL model reads the drafts for their claims, one draft per call, as a runtime gate would.

    B-021 step 3 asks whether the gate's word lists can be replaced by a local model writing down
    the claims of the reply it is shown, checked by python-chess. This scores that reader on the
    same drafts the judge and the agent read, so it can be held to the same stop rule.
    """
    reader = f"local_{args.model.replace(':', '_').replace('.', '_')}"
    provider = create_provider("ollama", model=args.model, base_url=args.base_url, timeout=600.0)
    for transcript in args.transcript:
        data = json.loads(Path(transcript).read_text(encoding="utf-8"))
        drafts = cl.drafts_of(data, seed=int(data["environment"]["seed"]))
        out_dir = Path(args.out) / Path(transcript).parent.name.replace("coach_review_", "")
        out_dir.mkdir(parents=True, exist_ok=True)
        replies: list[dict] = []  # type: ignore[type-arg]
        reading: dict[str, cl.ReadDraft] = {}
        for n, d in enumerate(drafts, start=1):
            prompt = cl.build_claims_prompt([d])
            t0 = time.perf_counter()
            reply = ""
            for _attempt in range(2):
                reply = provider.generate(prompt, max_tokens=args.max_tokens, temperature=0.0)
                try:
                    reading.update(cl.parse_claims_reply(reply))
                    break
                except cl.ClaimsParseError:
                    continue
            seconds = time.perf_counter() - t0
            replies.append({"id": d.id, "seconds": round(seconds, 1), "reply": reply})
            print(f"  progress={n}/{len(drafts)} {d.id} {seconds:.1f}s")
        (out_dir / f"claims_reply_{reader}.json").write_text(json.dumps(replies, indent=2), encoding="utf-8")
        scored = cl.score_reading(drafts, reading)
        verdicts = [s["verdict"] for s in scored.values()]
        summary = {v: verdicts.count(v) for v in (cl.FALSE, cl.CLEAN, cl.UNRESOLVED, cl.MISSING)}
        record = {"reader": reader, "transcript": transcript, "summary": summary, "drafts": scored}
        (out_dir / f"claims_{reader}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(f"{transcript}: {reader} {summary}, {sum(r['seconds'] for r in replies):.0f}s")


def _gate_blocks(entry: dict) -> bool:  # type: ignore[type-arg]
    """Does today's gate block this draft? The shipping gate's call, with the played move."""
    played = chess.Board(entry["fen_before"]).parse_san(entry["student_move_san"]).uci()
    return bool(gating_violations(check_text_fidelity(entry["text"], entry["fen_before"], played_uci=played)))


def _claims_compare(args: argparse.Namespace) -> None:
    """Pool readings across run directories; compare readers, then grade today's gate against each."""
    readers = [r.strip() for r in args.readers.split(",") if r.strip()]
    pooled: dict[str, dict[str, dict]] = {r: {} for r in readers}  # type: ignore[type-arg]
    for d in args.claims_compare:
        for r in readers:
            path = Path(d) / f"claims_{r}.json"
            if path.exists():
                pooled[r].update(json.loads(path.read_text(encoding="utf-8"))["drafts"])
    for r in readers:
        verdicts = [e["verdict"] for e in pooled[r].values()]
        counts = {v: verdicts.count(v) for v in (cl.FALSE, cl.CLEAN, cl.UNRESOLVED, cl.MISSING)}
        print(f"{r}: {len(verdicts)} drafts {counts}")
    for i, a in enumerate(readers):
        for b in readers[i + 1 :]:
            compared, differ = cl.disagreements(
                {k: e["verdict"] for k, e in pooled[a].items()}, {k: e["verdict"] for k, e in pooled[b].items()}
            )
            print(f"{a} vs {b}: {len(differ)} of {compared} drafts called false by one only: {differ}")
    for r in readers:
        table = {(True, True): 0, (True, False): 0, (False, True): 0, (False, False): 0}
        passed_false: list[str] = []
        blocked_clean: list[str] = []
        for k, e in sorted(pooled[r].items()):
            if e["verdict"] == cl.MISSING:
                continue
            is_false, blocks = e["verdict"] == cl.FALSE, _gate_blocks(e)
            table[(is_false, blocks)] += 1
            if is_false and not blocks:
                passed_false.append(k)
            if blocks and not is_false:
                blocked_clean.append(k)
        print(
            f"gate against {r}: false & blocked {table[(True, True)]}, false & passed {table[(True, False)]}, "
            f"not false & blocked {table[(False, True)]}, not false & passed {table[(False, False)]}"
        )
        print(f"  false drafts the gate passed: {passed_false}")
        print(f"  drafts the gate blocked that {r} found nothing false in: {blocked_clean}")


def _load(path: Path) -> tuple[list[ReviewTurn], ReviewStats]:
    data = json.loads(path.read_text(encoding="utf-8"))
    turns = [
        ReviewTurn(
            ply=t["ply"],
            phase=t["phase"],
            fen_before=t["fen_before"],
            student_move_san=t["student_move_san"],
            best_move_san=t["best_move_san"],
            classification=t["classification"],
            eval_drop_cp=t["eval_drop_cp"],
            coach_feedback=t["coach_feedback"],
            latency_s=t.get("latency_s", 0.0),
            fidelity_kinds=t.get("fidelity_kinds", {}) or {},
            prompt=t.get("prompt", "") or "",
        )
        for t in data["turns"]
    ]
    return turns, ReviewStats.from_dict(data["stats"])


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    p = argparse.ArgumentParser(description="Re-judge a saved report-card transcript")
    p.add_argument("--transcript", nargs="+", default=None, help="report-card transcript.json; several with --model")
    p.add_argument("--rubric", default="v2", help=f"comma-separated, from {RUBRIC_VERSIONS}")
    p.add_argument("--out", default="output/coach_rejudge")
    p.add_argument("--judge-model", default="claude-opus-5")
    p.add_argument("--judge-agent", default="judge-opus5")
    p.add_argument("--judge-command", default=None, help="defaults to kiro-cli with --judge-model")
    p.add_argument("--judge-base-url", default="http://localhost:11434")
    p.add_argument("--claims", action="store_true", help="B-021: read the drafts for their board claims")
    p.add_argument("--runs", type=int, default=1, help="with --claims: how many judge readings")
    p.add_argument("--claims-reply", default=None, help="with --claims: score this reply instead of calling the judge")
    p.add_argument("--reader", default="agent", help="with --claims-reply: the reader's name")
    p.add_argument("--claims-compare", nargs="+", default=None, metavar="DIR", help="compare scored readings")
    p.add_argument("--readers", default="judge_r1,judge_r2,agent", help="with --claims-compare")
    p.add_argument("--model", default=None, help="with --claims: a LOCAL Ollama model reads, one draft per call")
    p.add_argument("--base-url", default="http://localhost:11435", help="with --model")
    p.add_argument("--max-tokens", type=int, default=2048, help="with --model")
    args = p.parse_args()

    if args.claims_compare:
        _claims_compare(args)
        return
    if not args.transcript:
        p.error("--transcript is required unless comparing readings")
    if args.claims and args.model:
        _claims_local(args)
        return
    if len(args.transcript) != 1:
        p.error("one --transcript, unless a local --model is reading")
    args.transcript = args.transcript[0]
    if args.claims:
        _claims(args)
        return

    rubrics = [r.strip() for r in args.rubric.split(",") if r.strip()]
    unknown = [r for r in rubrics if r not in RUBRIC_VERSIONS]
    if unknown:
        print(f"FATAL: unknown rubric(s) {unknown}; expected from {RUBRIC_VERSIONS}")
        sys.exit(2)

    turns, stats = _load(Path(args.transcript))
    print(f"Loaded {len(turns)} coached turns from {args.transcript}")

    judge = _judge(args)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, rubric in enumerate(rubrics, start=1):
        prompt = build_coach_review_prompt(turns, stats, rubric=rubric)
        (out_dir / f"prompt_{rubric}.txt").write_text(prompt, encoding="utf-8")
        print(f"progress={i}/{len(rubrics)} judging with rubric {rubric} ({len(prompt)} chars)")
        t0 = time.perf_counter()
        try:
            review = judge.generate(prompt)
        except Exception as e:  # noqa: BLE001
            review = f"FAILED: {type(e).__name__}: {e}"
        dt = time.perf_counter() - t0
        dest = out_dir / f"review_{rubric}.md"
        dest.write_text(review, encoding="utf-8")
        print(f"  rubric {rubric} done in {dt:.0f}s -> {dest} ({len(review)} chars)")
    print(f"progress={len(rubrics)}/{len(rubrics)} complete")


if __name__ == "__main__":
    main()
