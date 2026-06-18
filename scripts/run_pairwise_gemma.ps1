# Pairwise A/B: gemma guidance OFF vs ON, over the saved 3x3 runs (judge-only,
# no tunnel). 3 dir-pairs x 9 positions = 27 randomized head-to-heads, judged by
# kiro-cli/claude-sonnet-4.6, summarized as a win-rate + two-sided sign test.
$ErrorActionPreference = "Continue"
$judge = "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
uv run python scripts/eval_pairwise.py `
    --a output/eval_rpt_gemma_off_1 output/eval_rpt_gemma_off_2 output/eval_rpt_gemma_off_3 `
    --b output/eval_rpt_gemma_on_1  output/eval_rpt_gemma_on_2  output/eval_rpt_gemma_on_3 `
    --label-a off --label-b on `
    --judge-provider cli --judge-model claude-sonnet-4.6 --judge-command $judge `
    --out output/eval_pairwise_gemma
Write-Output "===== PAIRWISE DONE ====="
