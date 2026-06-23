# Move-feedback pairwise A/B: guidance OFF vs ON over the move_feedback.yaml
# situations (20). Generation over the tunnel; judge via kiro-cli, repeated 5x
# per pair and majority-voted to denoise the judge. Run under kiro-monitor so
# output.log captures everything (the kiro-cli judge subprocess otherwise eats
# console output) and we get a completion toast.
param(
    [string]$Model = "gemma4:12b-it-qat",
    [string]$Out = "output/eval_mf_pairwise_gemma"
)
$ErrorActionPreference = "Continue"
$judge = "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
uv run python scripts/eval_move_feedback_pairwise.py `
    --model $Model --base-url http://localhost:11435 `
    --guidance-max 3 --judge-repeats 5 `
    --judge-provider cli --judge-model claude-sonnet-4.6 --judge-command $judge `
    --out $Out
Write-Output "===== MOVE-FEEDBACK PAIRWISE DONE ($Model) ====="
