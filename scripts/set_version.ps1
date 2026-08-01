# 앱 버전을 한 번에 맞춥니다. 버전이 네 곳에 흩어져 있어 하나만 빠뜨리면
# 자동 업데이트가 조용히 동작하지 않습니다.
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\set_version.ps1 1.1.0

param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

function Set-FileText {
    param([string]$Path, [string]$Pattern, [string]$Replacement)

    $full = Join-Path $projectRoot $Path
    $raw = [System.IO.File]::ReadAllText($full)
    if ($raw -notmatch $Pattern) {
        throw "$Path 에서 버전을 찾지 못했습니다."
    }
    $next = [regex]::Replace($raw, $Pattern, $Replacement, 1)
    [System.IO.File]::WriteAllText($full, $next)
    Write-Host "  $Path"
}

Write-Host "버전을 $Version 으로 맞춥니다."

Set-FileText "package.json"              '"version":\s*"\d+\.\d+\.\d+"'  ('"version": "{0}"' -f $Version)
Set-FileText "src-tauri\tauri.conf.json" '"version":\s*"\d+\.\d+\.\d+"'  ('"version": "{0}"' -f $Version)
Set-FileText "src-tauri\Cargo.toml"      '(?m)^version = "\d+\.\d+\.\d+"' ('version = "{0}"' -f $Version)
Set-FileText "src-tauri\Cargo.lock"      '(?m)(name = "jbedu-automation-suite"\r?\nversion = )"\d+\.\d+\.\d+"' ('$1"{0}"' -f $Version)

Write-Host ""
Write-Host "다음 단계:"
Write-Host "  git add -A"
Write-Host "  git commit -m `"chore: 버전 $Version`""
Write-Host "  git tag v$Version"
Write-Host "  git push && git push --tags"
