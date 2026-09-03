# Open the EC2 SSM tunnel and run the coach report card without a gap in between.
#
# The tunnel drops if it sits idle between being opened and being used, so the
# readiness loop and the run must live in one process: as soon as a real HTTP
# request confirms the model is loaded, the eval starts immediately. A port check
# alone is not enough — the port answers before Ollama does.
param(
    # Which driver to run once the tunnel is confirmed. Defaults to the report card;
    # any script taking --model/--base-url/--out works (e.g. eval_check_breadth.py).
    [string]$Script = "scripts/eval_coach_review.py",
    # Extra flags for the driver, as ONE string: "--config config.template_only.yaml".
    # Deliberately not string[]: passed as separate tokens, PowerShell reads a
    # leading "--flag" as a parameter name and silently binds the value that follows
    # to the next positional parameter — which set $Model to "queens-gambit" and made
    # the readiness loop wait three minutes for a model that does not exist.
    [string]$ScriptArgLine = "",
    [string]$Out = "output/coach_review_v25",
    [string]$Model = "qwen3:14b",
    [string]$BaseUrl = "http://localhost:11435",
    [int]$StudentElo = 1350,
    [int]$OpponentElo = 1500,
    [int]$PlyCap = 120,
    [int]$Seed = 7,
    [int]$ReadyTimeoutSeconds = 180
)
$ErrorActionPreference = "Continue"

function Test-ModelReady {
    param([string]$Url, [string]$Want)
    try {
        $r = Invoke-RestMethod -Uri "$Url/api/tags" -TimeoutSec 5
        return (($r.models | ForEach-Object { $_.name }) -contains $Want)
    } catch {
        return $false
    }
}

$tunnel = $null
if (-not (Test-ModelReady -Url $BaseUrl -Want $Model)) {
    Write-Host "tunnel down - opening"
    $tunnel = Start-Process -FilePath "C:\Tools\Git\usr\bin\bash.exe" `
        -ArgumentList "-lc", "~/ec2-ssm.sh" -WindowStyle Hidden -PassThru
} else {
    Write-Host "tunnel already up"
}

$deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
while (-not (Test-ModelReady -Url $BaseUrl -Want $Model)) {
    if ((Get-Date) -gt $deadline) {
        Write-Host "FATAL: $Model not ready at $BaseUrl after $ReadyTimeoutSeconds s"
        if ($tunnel) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
        exit 1
    }
    Start-Sleep -Seconds 3
}
Write-Host "$Model ready - starting run"

try {
    # $ScriptArgLine is honoured on BOTH branches. It used to be applied only to the
    # "other drivers" branch, so passing -ScriptArgLine alongside the default driver was
    # silently dropped: a template-only run launched with "--config config.template_only.yaml"
    # quietly produced another LLM run, and the only reason it was caught is that the output
    # was 11/18 byte-identical to the run it was supposed to be compared against.
    $extra = if ($ScriptArgLine) { $ScriptArgLine -split '\s+' } else { @() }
    if ($Script -eq "scripts/eval_coach_review.py") {
        uv run python $Script `
            --model $Model --base-url $BaseUrl `
            --student-elo $StudentElo --opponent-elo $OpponentElo `
            --ply-cap $PlyCap --seed $Seed --out $Out @extra
    } else {
        # Other drivers take the common flags plus whatever they need.
        uv run python $Script --model $Model --base-url $BaseUrl --out $Out @extra
    }
    $code = $LASTEXITCODE
} finally {
    if ($tunnel) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
}
exit $code
