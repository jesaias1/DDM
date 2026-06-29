Write-Host "Installerer Den Danske Metode dependencies..."

$python = Get-Command py -ErrorAction SilentlyContinue
if ($python) {
  py -m pip install -r requirements.txt
} else {
  python -m pip install -r requirements.txt
}

Write-Host ""
Write-Host "Faerdig. Start appen med:"
Write-Host "  .\START_DDM.ps1"
