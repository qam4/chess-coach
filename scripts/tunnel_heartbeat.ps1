# Keep the SSM port-forward warm during idle phases.
#
# The laptop<->AWS SSM WebSocket gets reset by the network path when it goes
# idle (confirmed: the EC2 box is healthy and receives zero requests once the
# tunnel drops — see docs/model-profiler.md). During an eval's judge phase the
# tunnel carries no traffic for minutes and gets killed. A light periodic
# request keeps the connection alive so long runs survive.
#
# Run standalone (Ctrl-C to stop), or let the eval runners start it as a job.
param(
    [string]$Url = "http://localhost:11435/api/tags",
    [int]$IntervalSeconds = 15
)
while ($true) {
    try { Invoke-RestMethod -Uri $Url -TimeoutSec 10 | Out-Null } catch {}
    Start-Sleep -Seconds $IntervalSeconds
}
