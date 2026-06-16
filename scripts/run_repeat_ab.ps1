# Repeat-run A/B driver: gemma4:12b-it-qat, 3x off + 3x on, rubric.v2,
# kiro-cli (claude-sonnet-4.6) judge, 9-position benchmark.
#
# Temperature is the eval default (0.0), so the model-under-test output is
# deterministic across repeats -- the variation captured here is JUDGE
# noise. That is exactly the noise band eval_aggregate.py needs to decide
# whether the off->on quality delta is real. Each run lands in its own dir.
$ErrorActionPreference = "Continue"
$base   = "http://localhost:11435"
$judge  = "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
$rubric = "data/eval/rubric.v2.yaml"
$model  = "gemma4:12b-it-qat"

for ($i = 1; $i -le 3; $i++) {
    Write-Output "===== REPEAT $i / 3 : OFF ====="
    uv run python scripts/eval_run.py --models $model --base-url $base `
        --guidance off --rubric $rubric `
        --judge-provider cli --judge-model claude-sonnet-4.6 --judge-command $judge `
        --out "output/eval_rpt_gemma_off_$i"

    Write-Output "===== REPEAT $i / 3 : ON (max 3) ====="
    uv run python scripts/eval_run.py --models $model --base-url $base `
        --guidance on --guidance-max 3 --rubric $rubric `
        --judge-provider cli --judge-model claude-sonnet-4.6 --judge-command $judge `
        --out "output/eval_rpt_gemma_on_$i"
}
Write-Output "===== ALL 6 RUNS DONE ====="
