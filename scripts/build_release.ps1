param(
    [string]$SigningKey = ".signing\tauri.key"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$signingKeyPath = (Resolve-Path -LiteralPath (Join-Path $projectRoot $SigningKey)).Path
$signingPasswordPath = (Resolve-Path -LiteralPath (Join-Path $projectRoot ".signing\tauri.password")).Path
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
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -Raw -LiteralPath $signingKeyPath
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = Get-Content -Raw -LiteralPath $signingPasswordPath

Set-Location -LiteralPath $projectRoot
npm.cmd run tauri:build

