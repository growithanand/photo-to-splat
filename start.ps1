$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/'
    Write-Host 'Reopen this terminal, then run this launcher again.'
    exit 1
}
uv sync --locked --no-dev
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --locked --no-dev photosplat ui
