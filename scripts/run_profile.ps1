# Run the model-capability profiler for a model, judged by kiro-cli (sonnet).
# Generation over the tunnel; the guidance dimension runs the ~30-min pairwise
# A/B, so run under kiro-monitor (output.log captures the kiro-cli judge output
# and we get a completion toast).
param(
    [string]$Model = "qwen3:14b"
)
$ErrorActionPreference = "Continue"
$judge = "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
uv run python scripts/profile_model.py `
    --model $Model --base-url http://localhost:11435 `
    --judge-provider cli --judge-model claude-sonnet-4.6 --judge-command $judge
Write-Output "===== PROFILE DONE ($Model) ====="
