# Re-test: qwen3:14b 3x ON with the TIGHTENED guidance intro (anti-fabrication
# clause). The OFF runs don't use the guidance block, so the existing
# output/eval_rpt_qwen_off_{1,2,3} baseline still applies -- we only need
# fresh ON runs. New dirs (qwen2) so we can compare against the OLD ON runs
# (qwen_on_*, pre-tightening) and the shared OFF baseline.
$ErrorActionPreference = "Continue"
$base   = "http://localhost:11435"
$judge  = "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
$rubric = "data/eval/rubric.v2.yaml"
$model  = "qwen3:14b"

for ($i = 1; $i -le 3; $i++) {
    Write-Output "===== qwen2 ON RETEST $i / 3 ====="
    uv run python scripts/eval_run.py --models $model --base-url $base `
        --guidance on --guidance-max 3 --rubric $rubric `
        --judge-provider cli --judge-model claude-sonnet-4.6 --judge-command $judge `
        --out "output/eval_rpt_qwen2_on_$i"
}
Write-Output "===== qwen2 ON RETEST DONE ====="
