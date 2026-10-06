$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$root = $PSScriptRoot
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Path $dist -Force | Out-Null
$path = Join-Path $dist ("DDM-Terminal-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".zip")
$files = @("app.py", "requirements.txt", "README.md", "CLAUDE.md", ".gitignore",
    "INSTALL_DDM.ps1", "START_DDM.ps1", "START_DDM.bat", "PACKAGE_DDM.ps1",
    "DDM_ENV_TEMPLATE.ps1", "START_HER_STATIONAER.txt") | ForEach-Object { Get-Item -LiteralPath (Join-Path $root $_) }
foreach ($folder in @("engine", "templates", "static", "tests", "docs")) {
    $files += Get-ChildItem -LiteralPath (Join-Path $root $folder) -File -Recurse |
        Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -notin @('.pyc', '.pyo') }
}
$archive = [System.IO.Compression.ZipFile]::Open($path, 'Create')
try {
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($root.Length + 1).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $relative, 'Optimal') | Out-Null
    }
    $archive.CreateEntry('data/') | Out-Null
} finally { $archive.Dispose() }
Write-Host "Pakke: $path"
Write-Host "Kode, assets, tests og dokumentation. Ingen kontodata, noegler eller Python-runtime."
