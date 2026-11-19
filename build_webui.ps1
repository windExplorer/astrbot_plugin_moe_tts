# 构建萌萌语音 WebUI：从 metadata.yaml 注入版本号到 src/version.ts，再 vite build。
# 输出 pages/moe-tts/（入库，zip 依赖）。
# 不能用 Stop：npm/vite 会把彩色进度写到 stderr，PowerShell 会误判为 terminating error
# （曾导致构建实际成功却报 "Build failed"，进而打进旧产物）。改用显式 $LASTEXITCODE 判定。
$ErrorActionPreference = "Continue"
if ($PSScriptRoot) { $root = $PSScriptRoot } elseif ($MyInvocation.MyCommand.Path) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path } else { $root = (Get-Location).Path }
$webui = Join-Path $root "webui-src"

# 读版本号（显式 UTF-8）
$metaPath = Join-Path $root "metadata.yaml"
$version = "v0.1.0"
if (Test-Path $metaPath) {
    $meta = [System.IO.File]::ReadAllText($metaPath, [System.Text.Encoding]::UTF8)
    if ($meta -match 'version:\s*(v?[0-9]+\.[0-9]+\.[0-9]+)') { $version = $Matches[1] }
}
Write-Host "Using version $version"

$versionFile = Join-Path $webui "src\version.ts"
$versionTs = "export const PLUGIN_VERSION = `"$version`";`n"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($versionFile, $versionTs, $utf8)

if (-not (Test-Path (Join-Path $webui "node_modules"))) {
    Write-Host "Installing dependencies..."
    Push-Location $webui
    npm install 2>&1 | Select-Object -Last 8
    Pop-Location
}

Push-Location $webui
# 先捕获到变量再输出：既保留完整日志，又让 $LASTEXITCODE 反映 npm 的真实退出码
$buildLog = & npm run build 2>&1 | Out-String
$code = $LASTEXITCODE
Write-Host ($buildLog -split "`n" | Select-Object -Last 12 | Out-String)
if ($code -ne 0) { Write-Host "Build failed (exit $code)" -ForegroundColor Red; Pop-Location; exit 1 }
Pop-Location
Write-Host "WebUI built -> pages/moe-tts/"
