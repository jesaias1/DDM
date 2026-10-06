$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
Write-Host "Installerer Den Danske Metode i lokal .venv..."
if (-not (Test-Path -LiteralPath "$PSScriptRoot\.venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv }
    else { python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ kraeves. Oprettelse af .venv fejlede." }
}
& "$PSScriptRoot\.venv\Scripts\python.exe" -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Installation fejlede. Se fejlene ovenfor." }
Write-Host "Faerdig. Start med .\START_DDM.ps1"
