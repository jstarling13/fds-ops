Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.+)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
    }
}

$apiKey = [System.Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY")

$body = @{
    model      = "claude-sonnet-4-20250514"
    max_tokens = 2000
    messages   = @(@{
        role    = "user"
        content = "You are a market analyst. List the top 12 independent (non-franchise) business niches in Columbus GA that would most need SBA loans, bank financing packages, business valuations, or CIMs to sell. Score each 1-10 for fit with a financial document firm. Return ONLY a JSON array with keys: rank, niche, fit_score, primary_fds_service, avg_revenue_range, why_columbus, typical_trigger. No markdown."
    })
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod -Uri "https://api.anthropic.com/v1/messages" -Method POST -Headers @{"x-api-key"=$apiKey;"anthropic-version"="2023-06-01";"content-type"="application/json"} -Body $body

$niches = $response.content[0].text.Trim() | ConvertFrom-Json

foreach ($n in $niches) {
    $c = if ($n.fit_score -ge 8) {"Green"} elseif ($n.fit_score -ge 6) {"Yellow"} else {"Gray"}
    Write-Host "#$($n.rank) $($n.niche) — $($n.fit_score)/10" -ForegroundColor $c
    Write-Host "    Service: $($n.primary_fds_service)" -ForegroundColor Cyan
    Write-Host "    Trigger: $($n.typical_trigger)" -ForegroundColor DarkGray
    Write-Host ""
}

$niches | ConvertTo-Json -Depth 5 | Out-File "data\niches.json" -Encoding UTF8
