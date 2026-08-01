# 설치하지 않고 개발 모드로 앱을 띄웁니다.
# 화면(React)을 고치면 저장하는 순간 창에 바로 반영됩니다.
# 종료하려면 이 창에서 Ctrl+C 를 누르세요.

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$devShellModule = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\Microsoft.VisualStudio.DevShell.dll"
$cargoBin = "C:\Users\kain9\.cargo\bin"

if (-not (Test-Path -LiteralPath $devShellModule)) {
    throw "Microsoft C++ Build Tools를 찾지 못했습니다."
}

Import-Module $devShellModule
Enter-VsDevShell `
    -VsInstallPath "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools" `
    -SkipAutomaticLocation `
    -DevCmdArguments "-arch=x64"

$env:PATH = "$cargoBin;$env:PATH"

Set-Location -LiteralPath $projectRoot
npm.cmd run tauri:dev
