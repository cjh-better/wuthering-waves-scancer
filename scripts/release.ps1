param(
    [string]$Version = "3.0.0",
    [string]$ResultRoot = "K:\result",
    [switch]$PublishGitHub
)

$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$rootScript = Join-Path $repo "release.ps1"

if ($PublishGitHub) {
    & $rootScript -Version $Version -ResultRoot $ResultRoot -PublishGitHub
} else {
    & $rootScript -Version $Version -ResultRoot $ResultRoot
}
