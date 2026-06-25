# Run the model-capability profiler for a model, judged by kiro-cli (sonnet).
# Generation over the tunnel; the guidance dimension runs the ~30-min pairwise
# A/B, so run under kiro-monitor (output.log captures the kiro-cli judge output
# and we get a completion toast).
#
# A background heartbeat keeps the SSM tunnel warm through the judge phases
# (which don't touch the tunnel) so it doesn't get idle-reset mid-run.
param(
    [string]$Model = "qwen3:14b"
)
$ErrorActionPreference = "Continue"
$hb = Start-Job -FilePath (Join-Path $PSScriptRoot "tunnel_heartbeat.ps1")
try {
    $judge = "kiro-cli chat --no-interactive --model claude-sonnet-4.6 {prompt}"
    uv run python scripts/profile_model.py `
        --model $Model --base-url http://localhost:11435 `
        --judge-provider cli --judge-model claude-sonnet-4.6 --judge-command $judge
} finally {
    Stop-Job $hb -ErrorAction SilentlyContinue
    Remove-Job $hb -Force -ErrorAction SilentlyContinue
}
Write-Output "===== PROFILE DONE ($Model) ====="
