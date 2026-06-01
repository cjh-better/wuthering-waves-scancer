param(
    [string]$Version = "3.0.0",
    [string]$ResultRoot = "K:\result",
    [switch]$PublishGitHub
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$versionTag = "v$Version"
$packageName = "wuthering-waves-scancer-$versionTag"
$packageDir = Join-Path $ResultRoot $packageName
$zipPath = Join-Path $ResultRoot "$packageName.zip"
$python = Join-Path $repo ".venv\Scripts\python.exe"
$pyinstaller = Join-Path $repo ".venv\Scripts\pyinstaller.exe"
$releaseNotes = Join-Path $repo "RELEASE_NOTES_$versionTag.md"

if (-not (Test-Path $python)) {
    throw "Missing virtualenv Python: $python"
}
if (-not (Test-Path $pyinstaller)) {
    throw "Missing PyInstaller: $pyinstaller"
}
if (-not (Test-Path $releaseNotes)) {
    throw "Missing release notes: $releaseNotes"
}

Push-Location $repo
try {
    & $python -m pytest -q
    & $pyinstaller --clean --noconfirm mingchao_scanner.spec

    $exeSource = Get-ChildItem -LiteralPath (Join-Path $repo "dist") -Filter "*.exe" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $exeSource) {
        throw "PyInstaller did not produce an exe in dist."
    }

    New-Item -ItemType Directory -Force -Path $packageDir | Out-Null
    $exeTarget = Join-Path $packageDir "$($exeSource.BaseName)-$versionTag$($exeSource.Extension)"
    Copy-Item -LiteralPath $exeSource.FullName -Destination $exeTarget -Force
    Copy-Item -LiteralPath (Join-Path $repo "README.md") -Destination (Join-Path $packageDir "README.md") -Force
    Copy-Item -LiteralPath (Join-Path $repo "LICENSE") -Destination (Join-Path $packageDir "LICENSE") -Force
    Copy-Item -LiteralPath $releaseNotes -Destination (Join-Path $packageDir (Split-Path -Leaf $releaseNotes)) -Force

    $hashLines = Get-ChildItem -LiteralPath $packageDir -File |
        Where-Object { $_.Name -ne "SHA256SUMS.txt" } |
        Sort-Object Name |
        ForEach-Object {
            $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
            "$($hash.Hash)  $($_.Name)"
        }
    Set-Content -LiteralPath (Join-Path $packageDir "SHA256SUMS.txt") -Value $hashLines -Encoding UTF8

    Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath $zipPath -Force

    Write-Host "Release package:"
    Write-Host "  $packageDir"
    Write-Host "  $zipPath"

    if ($PublishGitHub) {
        if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
            throw "GitHub CLI (gh) is not installed."
        }
        gh release create $versionTag $zipPath --notes-file $releaseNotes --title "鸣潮抢码器 $versionTag"
    }
}
finally {
    Pop-Location
}
