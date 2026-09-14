param(
    [string]$SigningKey = ".signing\tauri.key",
    [switch]$SkipSidecar
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$signingKeyPath = (Resolve-Path -LiteralPath (Join-Path $projectRoot $SigningKey)).Path
$signingPasswordPath = (Resolve-Path -LiteralPath (Join-Path $projectRoot ".signing\tauri.password")).Path
$devShellModule = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\Microsoft.VisualStudio.DevShell.dll"
$cargoBin = "C:\Users\kain9\.cargo\bin"
$sidecarPath = Join-Path $projectRoot "src-tauri\binaries\bridge-runner-x86_64-pc-windows-msvc.exe"

if (-not (Test-Path -LiteralPath $devShellModule)) {
    throw "Microsoft C++ Build Tools를 찾지 못했습니다."
}

# 파이썬 도구는 설치본 안의 사이드카(bridge-runner.exe)로 돕니다. 이걸 새로 만들지
# 않으면 예전 exe가 그대로 들어가고, 제작자 PC는 소스의 runner.py 를 직접 쓰기 때문에
# 아무도 그 차이를 눈치채지 못합니다. 그래서 빌드 때마다 반드시 새로 만듭니다.
if ($SkipSidecar) {
    Write-Host "사이드카를 새로 만들지 않습니다. (-SkipSidecar)"
} else {
    Write-Host "사이드카(bridge-runner)를 새로 만듭니다. 몇 분 걸립니다."
    python -m PyInstaller --noconfirm --distpath src-tauri/binaries --workpath build-sidecar bridge/runner.spec
    if ($LASTEXITCODE -ne 0) {
        throw "사이드카 빌드에 실패했습니다. 위 메시지를 확인하세요."
    }
}

if (-not (Test-Path -LiteralPath $sidecarPath)) {
    throw "사이드카를 찾지 못했습니다: $sidecarPath"
}

# 사이드카가 파이썬 코드보다 오래되면 멈춥니다. 옛 동작이 담긴 설치본이
# 배포되는 일을 여기서 막습니다.
$sidecarTime = (Get-Item -LiteralPath $sidecarPath).LastWriteTime
$searchRoots = @(
    (Join-Path $projectRoot "bridge"),
    (Join-Path $projectRoot "tools")
) | Where-Object { Test-Path -LiteralPath $_ }

$newest = Get-ChildItem -LiteralPath $searchRoots -Recurse -Filter *.py -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notlike "*\__pycache__\*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($newest -and $newest.LastWriteTime -gt $sidecarTime) {
    $lines = @(
        "사이드카가 파이썬 코드보다 오래되었습니다. 이대로 배포하면 설치본만 옛 동작을 합니다.",
        "  사이드카  : $sidecarTime",
        "  최신 코드 : $($newest.LastWriteTime)",
        "              $($newest.FullName)",
        "-SkipSidecar 를 빼고 다시 실행하세요."
    )
    throw ($lines -join [Environment]::NewLine)
}

Write-Host "사이드카 확인: $sidecarTime"
Write-Host ""

Import-Module $devShellModule
Enter-VsDevShell `
    -VsInstallPath "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools" `
    -SkipAutomaticLocation `
    -DevCmdArguments "-arch=x64"

$env:PATH = "$cargoBin;$env:PATH"
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -Raw -LiteralPath $signingKeyPath
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = Get-Content -Raw -LiteralPath $signingPasswordPath

Set-Location -LiteralPath $projectRoot
npm.cmd run tauri:build
