"""Benchmark LLM models on the same coaching prompt."""

from chess_coach.engine import CoachingEngine
from chess_coach.prompts import build_rich_coaching_prompt
from chess_coach.llm.ollama import OllamaProvider
import os, time, sys

path = os.path.expanduser("~/src/fred/blunder/build/rel/blunder")
engine = CoachingEngine(path, args=["--uci"], ping_timeout=5.0, coaching_timeout=10.0)
engine.start()

fen = "r1bqkbnr/pppppppp/2n5/4P3/2B5/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
report = engine.get_position_report(fen, multipv=3)
prompt = build_rich_coaching_prompt(report, level="intermediate")
print(f"Prompt: {len(prompt)} chars\n")

models = sys.argv[1:] if len(sys.argv) > 1 else ["qwen3:1.7b", "qwen3:4b", "qwen3:8b"]

for model in models:
    print(f"--- {model} ---")
    llm = OllamaProvider(model=model, base_url="http://localhost:11434", timeout=300)

    print(f"  Warming up...")
    t_warm = time.perf_counter()
    _ = llm.generate("Say hi", max_tokens=10, temperature=0.7)
    print(f"  Warm: {time.perf_counter() - t_warm:.1f}s")

    t0 = time.perf_counter()
    result = llm.generate(prompt, max_tokens=512, temperature=0.7)
    t1 = time.perf_counter()
    print(f"  Time: {t1 - t0:.1f}s | Output: {len(result)} chars")
    print(f"  Response:\n{result}\n")

engine.stop()
print("Done!")
