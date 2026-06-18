# Sharpen-selection A/B: gemma4:12b-it-qat, 3x ON with --guidance-max 1
# (most-specific entry only) vs the existing cap-3 ON runs and the OFF baseline.
# Tests whether tighter SELECTION (fewer, more-specific entries) beats cap 3 --
# the lever to try after prompt-tightening backfired.
$ErrorActionPreference = "Continue"
$base   = "http://localhost:11435"
$judge  = "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
$rubric = "data/eval/rubric.v2.yaml"
$model  = "gemma4:12b-it-qat"

for ($i = 1; $i -le 3; $i++) {
    Write-Output "===== gemma cap1 ON $i / 3 ====="
    uv run python scripts/eval_run.py --models $model --base-url $base `
        --guidance on --guidance-max 1 --rubric $rubric `
        --judge-provider cli --judge-model claude-sonnet-4.6 --judge-command $judge `
        --out "output/eval_rpt_gemma_cap1_on_$i"
}
Write-Output "===== gemma cap1 DONE ====="
