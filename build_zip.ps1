# Package astrbot_plugin_moe_tts into an AstrBot-installable zip.
#
# Design notes (keep them, learned from sibling plugins):
#   1) EXPLICIT include list. New top-level .py modules MUST be added here,
#      otherwise the repo has the file but the released zip silently misses it.
#   2) Refuse to overwrite an existing zip of the same version: bump metadata.yaml
#      and add a CHANGELOG entry before repacking. Old zips in dist/ are kept.
#   3) Layout: wrapped in a top-level folder named after the plugin, with explicit
#      directory entries and forward slashes. Do NOT use Compress-Archive.
#   4) dist/ is git-ignored: zip is a local install artifact, not source.
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\build_zip.ps1
# NOTE: keep this file ASCII-only (PS 5.1 can mis-parse UTF-8 no-BOM CJK comments).

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

if ($PSScriptRoot) { $root = $PSScriptRoot }
elseif ($MyInvocation.MyCommand.Path) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }
else { $root = (Get-Location).Path }

$pluginName = "astrbot_plugin_moe_tts"
$distDir = Join-Path $root "dist"

# --- version from metadata.yaml (UTF8) ---
$metaPath = Join-Path $root "metadata.yaml"
if (-not (Test-Path $metaPath)) { Write-Host "ERROR: metadata.yaml not found" -ForegroundColor Red; exit 1 }
$metaRaw = Get-Content -Raw -Encoding UTF8 $metaPath
$version = ""
if ($metaRaw -match '(?m)^\s*version:\s*v?([0-9][^\s#]*)') { $version = $Matches[1].Trim() }
if (-not $version) { Write-Host "ERROR: cannot read version from metadata.yaml" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $distDir)) { New-Item -ItemType Directory -Path $distDir | Out-Null }
$zipName = "${pluginName}_v${version}.zip"
$zipPath = Join-Path $distDir $zipName
if (Test-Path $zipPath) {
    Write-Host "ERROR: $zipName already exists. Bump 'version' in metadata.yaml and add a CHANGELOG entry before repacking." -ForegroundColor Red
    exit 1
}

# --- release contents (explicit include list) ---
$includeList = @(
    "main.py",
    "server.py",
    "store.py",
    "avatar.py",
    "contacts.py",
    "textutil.py",
    "tts_engine.py",
    "translator.py",
    "tts_api.py",
    "webapi.py",
    "_conf_schema.json",
    "metadata.yaml",
    "logo.png",
    "README.md",
    "CHANGELOG.md",
    "docs",
    "skills",
    "pages"
)

# --- self-check: every top-level .py MUST be listed above ---
$topPy = @(Get-ChildItem $root -Filter *.py -File | Select-Object -ExpandProperty Name)
$notListed = @($topPy | Where-Object { $includeList -notcontains $_ })
if ($notListed.Count -gt 0) {
    Write-Host ("ERROR: top-level module(s) missing from includeList: " + ($notListed -join ", ")) -ForegroundColor Red
    exit 1
}
Write-Host ("includeList check OK: all " + $topPy.Count + " top-level .py files are listed")

# Built console must exist before packaging.
$consoleIndex = Join-Path $root "pages/moe-tts/index.html"
if (-not (Test-Path $consoleIndex)) {
    Write-Host "ERROR: pages/moe-tts/index.html missing. Run .\build_webui.ps1 first." -ForegroundColor Red
    exit 1
}

function Add-ItemToZip($zip, $fsPath, $entryPath) {
    if (Test-Path -PathType Container $fsPath) {
        $null = $zip.CreateEntry($entryPath + "/")
        Get-ChildItem $fsPath |
            Where-Object { $_.Name -ne "__pycache__" -and $_.Extension -notin @(".pyc", ".pyo") } |
            ForEach-Object { Add-ItemToZip $zip $_.FullName ($entryPath + "/" + $_.Name) }
    } else {
        $entry = $zip.CreateEntry($entryPath, [System.IO.Compression.CompressionLevel]::Optimal)
        $stream = $entry.Open()
        try {
            $bytes = [System.IO.File]::ReadAllBytes($fsPath)
            $stream.Write($bytes, 0, $bytes.Length)
        } finally { $stream.Dispose() }
    }
}

$fs = [System.IO.File]::Open($zipPath, [System.IO.FileMode]::Create)
$zip = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Create, $false)
try {
    foreach ($name in $includeList) {
        $fsPath = Join-Path $root $name
        if (-not (Test-Path $fsPath)) {
            Write-Host "ERROR: missing required item: $name" -ForegroundColor Red
            $zip.Dispose(); $fs.Dispose()
            Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
            exit 1
        }
        Add-ItemToZip $zip $fsPath ($pluginName + "/" + $name)
    }
} finally { $zip.Dispose(); $fs.Dispose() }

$entries = @(tar -tf $zipPath)
$sizeKb = [math]::Round((Get-Item $zipPath).Length / 1024, 1)
Write-Host "Packaged: $zipPath" -ForegroundColor Green
Write-Host ("Entries : {0}   Size: {1} KB" -f $entries.Count, $sizeKb)

$top = @($entries | ForEach-Object { ($_ -split '/')[0] } | Sort-Object -Unique)
Write-Host ("Top-level: " + ($top -join ","))
if ($top.Count -eq 1 -and $top[0] -eq $pluginName) {
    Write-Host "OK: wrapped layout as expected." -ForegroundColor Green
} else {
    Write-Host "WARN: unexpected archive layout, check packaging!" -ForegroundColor Yellow
}
