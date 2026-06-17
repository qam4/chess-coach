# One-off top-up: the qwen3:14b 3x3 run lost runs to a mid-job tunnel drop.
# We already have off_1, off_2, on_1. This fills the gaps in ON-first order
# (ON is the deficient side; need >=2 ON for an assessable band) so that an
# early tunnel drop still leaves the most useful data.
$ErrorActionPreference = "Continue"
$base   = "http://localhost:11435"
$judge  = "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
$rubric = "data/eval/rubric.v2.yaml"
$model  = "qwen3:14b"

$jobs = @(
    @{ guidance = "on";  out = "output/eval_rpt_qwen_on_2" },
    @{ guidance = "on";  out = "output/eval_rpt_qwen_on_3" },
    @{ guidance = "off"; out = "output/eval_rpt_qwen_off_3" }
)
foreach ($j in $jobs) {
    Write-Output "===== TOPUP $($j.guidance) -> $($j.out) ====="
    $extra = @()
    if ($j.guidance -eq "on") { $extra = @("--guidance-max", "3") }
    uv run python scripts/eval_run.py --models $model --base-url $base `
        --guidance $j.guidance @extra --rubric $rubric `
        --judge-provider cli --judge-model claude-sonnet-4.6 --judge-command $judge `
        --out $j.out
}
Write-Output "===== TOPUP DONE ====="
