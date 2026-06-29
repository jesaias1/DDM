$ErrorActionPreference = "Stop"

if (Test-Path ".\.env.local.ps1") {
  Write-Host "Indlaeser .env.local.ps1..."
  . ".\.env.local.ps1"
} else {
  Write-Host "Ingen .env.local.ps1 fundet. Starter i toer-koersel uden rigtige handler."
  Write-Host "Kopier DDM_ENV_TEMPLATE.ps1 til .env.local.ps1 for live/Coinbase."
}

$python = Get-Command py -ErrorAction SilentlyContinue
if ($python) {
  py app.py
} else {
  python app.py
}
