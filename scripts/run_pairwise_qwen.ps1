# Pairwise A/B: qwen3:14b guidance OFF vs ON (cap-3), over the saved 3x3 runs.
# qwen generation is non-deterministic, so the 3 dir-pairs give genuine response
# diversity -> 27 head-to-heads with truer independence than gemma's. Judge-only
# (kiro-cli/claude-sonnet-4.6), no tunnel. The single-run absolute scores hinted
# qwen's teaching improved with guidance (0.12->0.22) at a factual cost; this
# tests whether the teaching edge survives a low-noise head-to-head.
$ErrorActionPreference = "Continue"
$judge = "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
uv run python scripts/eval_pairwise.py `
    --a output/eval_rpt_qwen_off_1 output/eval_rpt_qwen_off_2 output/eval_rpt_qwen_off_3 `
    --b output/eval_rpt_qwen_on_1  output/eval_rpt_qwen_on_2  output/eval_rpt_qwen_on_3 `
    --label-a off --label-b on `
    --judge-provider cli --judge-model claude-sonnet-4.6 --judge-command $judge `
    --out output/eval_pairwise_qwen
Write-Output "===== PAIRWISE QWEN DONE ====="
