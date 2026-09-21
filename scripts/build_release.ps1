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
# 사이드카를 만들기 전에 준비물부터 본다. 없으면 PyInstaller 가 알아듣기 힘든
# 메시지를 내고 멈추므로, 무엇이 없는지 여기서 먼저 짚어 준다.
$runnerPath = Join-Path $projectRoot "bridge\runner.py"
if (-not (Test-Path -LiteralPath $runnerPath)) {
    $hint = ""
    if (Test-Path -LiteralPath "$runnerPath.bak") {
        $hint = "`n  bridge\runner.py.bak 이 있습니다. 확인용으로 이름을 바꿔 두셨다면 되돌리세요:`n  Rename-Item .\bridge\runner.py.bak runner.py"
    }
    throw "bridge\runner.py 가 없습니다.$hint"
}

$gsExe = Join-Path $projectRoot "vendor\gs\bin\gswin64c.exe"
if (-not (Test-Path -LiteralPath $gsExe)) {
    throw ("vendor\gs\bin\gswin64c.exe 가 없습니다. PDF 압축용 Ghostscript 입니다." + [Environment]::NewLine +
           "  C:\work\pdf_doc_tools_tk\gs 폴더를 vendor\gs 로 복사하세요.")
}

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

# 사이드카로 모든 파이썬 도구를 실제로 불러와 본다. 빌드에서 빠진 라이브러리는
# 그 도구를 누가 처음 누를 때에야 드러나므로(reportlab.pdfbase, Ghostscript),
# 여기서 하나라도 실패하면 배포를 멈춘다. 앱이 도구를 돌릴 때와 같은 환경값을 준다.
Write-Host "사이드카 자가검사를 합니다."
$toolsRoot = Join-Path $projectRoot "tools"
$previousEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:JBEDU_TOOLS_ROOT = $toolsRoot
$env:JBEDU_PROJECT_ROOT = $toolsRoot
$selftest = & $sidecarPath --selftest 2>&1
$selftestCode = $LASTEXITCODE
[Console]::OutputEncoding = $previousEncoding
Remove-Item Env:JBEDU_TOOLS_ROOT -ErrorAction SilentlyContinue
Remove-Item Env:JBEDU_PROJECT_ROOT -ErrorAction SilentlyContinue
$selftest | ForEach-Object { Write-Host "  $_" }
if ($selftestCode -ne 0) {
    throw "사이드카 자가검사에 실패했습니다. 위 failed 항목의 도구는 설치본에서 동작하지 않습니다."
}
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
