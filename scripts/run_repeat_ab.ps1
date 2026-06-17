# Repeat-run A/B driver: N x off + N x on for one model, rubric.v2,
# kiro-cli (claude-sonnet-4.6) judge, 9-position benchmark.
#
# Temperature is the eval default (0.0), so the model-under-test output is
# deterministic across repeats -- the variation captured here is JUDGE
# noise. That is exactly the noise band eval_aggregate.py needs to decide
# whether the off->on quality delta is real. Each run lands in its own dir
# named output/eval_rpt_<tag>_{off,on}_<i>.
#
# Usage (defaults to gemma):
#   powershell -File scripts/run_repeat_ab.ps1 -Model qwen3:14b -Tag qwen -Repeats 3
param(
    [string]$Model   = "gemma4:12b-it-qat",
    [string]$Tag     = "gemma",
    [int]   $Repeats = 3
)
$ErrorActionPreference = "Continue"
$base   = "http://localhost:11435"
$judge  = "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
$rubric = "data/eval/rubric.v2.yaml"

for ($i = 1; $i -le $Repeats; $i++) {
    Write-Output "===== $Tag REPEAT $i / $Repeats : OFF ====="
    uv run python scripts/eval_run.py --models $Model --base-url $base `
        --guidance off --rubric $rubric `
        --judge-provider cli --judge-model claude-sonnet-4.6 --judge-command $judge `
        --out "output/eval_rpt_${Tag}_off_$i"

    Write-Output "===== $Tag REPEAT $i / $Repeats : ON (max 3) ====="
    uv run python scripts/eval_run.py --models $Model --base-url $base `
        --guidance on --guidance-max 3 --rubric $rubric `
        --judge-provider cli --judge-model claude-sonnet-4.6 --judge-command $judge `
        --out "output/eval_rpt_${Tag}_on_$i"
}
Write-Output "===== ALL $($Repeats * 2) RUNS DONE ($Tag) ====="
