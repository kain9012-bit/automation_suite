# 게시글에 붙여 넣을 [업데이트정보] 표식 한 줄을 만듭니다.
#
# 서명은 448자짜리 base64라 손으로 옮겨 적으면 거의 틀립니다. 한 글자만
# 어긋나도 설치가 거부되므로, 이 스크립트가 만든 줄을 그대로 붙여 넣으세요.
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\print_board_marker.ps1 `
#       -Version 1.2.5 -DownloadUrl "https://www.jbe.go.kr/board/download.jbe?...&fileSid=123456"
#
# 설치본을 GitHub Releases에서 받아 쓸 때는 .sig 파일 경로를 직접 줍니다.
#
#   ... -SignaturePath C:\Users\kain9\Downloads\JB업무ON_1.2.5_x64-setup.exe.sig
#
# 게시글에 ZIP을 첨부해 저장한 뒤, 그 첨부 링크를 우클릭해 주소를 복사하고
# -DownloadUrl 로 넘기세요. 만들어진 한 줄은 클립보드에도 들어갑니다.

param(
    [string]$Version,
    [string]$SignaturePath,
    [string]$AppId = "JBEDT-0005",
    [string]$AppName = "JB업무ON",
    # 게시글에 올린 설치본 ZIP의 첨부 링크 주소.
    # 첨부를 다시 올리면 fileSid 가 바뀌므로 매번 새로 복사해 넘긴다.
    [string]$DownloadUrl = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

# 버전을 안 주면 package.json에서 읽는다.
if (-not $Version) {
    $package = Get-Content (Join-Path $projectRoot "package.json") -Raw | ConvertFrom-Json
    $Version = $package.version
}

# 서명 파일을 안 주면 빌드 결과에서 찾는다.
if (-not $SignaturePath) {
    $bundle = Join-Path $projectRoot "src-tauri\target\release\bundle\nsis"
    if (-not (Test-Path -LiteralPath $bundle)) {
        throw "빌드 결과 폴더가 없습니다. .sig 파일 경로를 -SignaturePath 로 주세요."
    }
    $found = Get-ChildItem -LiteralPath $bundle -Filter "*.sig" |
        Sort-Object LastWriteTime -Descending
    if (-not $found) {
        throw "서명(.sig) 파일을 찾지 못했습니다. -SignaturePath 로 직접 주세요."
    }
    $SignaturePath = $found[0].FullName
}

$signature = (Get-Content -LiteralPath $SignaturePath -Raw).Trim()

if ($signature -match '[\|\r\n]') {
    throw "서명에 | 나 줄바꿈이 섞여 있습니다. 올바른 .sig 파일인지 확인하세요."
}

# 서명 안에는 어느 파일에 서명한 것인지가 적혀 있다. 게시판에 올린 ZIP 속 exe와
# 다른 파일의 서명을 넣는 것이 가장 흔한 실수라, 여기서 미리 보여 준다.
$signedFile = ""
try {
    $decoded = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($signature))
    foreach ($line in $decoded -split "`n") {
        if ($line -like "trusted comment:*" -and $line -match 'file:(.+?)(\t|$)') {
            $signedFile = $Matches[1].Trim()
        }
    }
} catch {
    throw "서명 파일을 해석하지 못했습니다. 올바른 .sig 파일인지 확인하세요."
}

if (-not $DownloadUrl) {
    throw "첨부 링크 주소가 필요합니다. 게시글에 ZIP을 올린 뒤 그 링크를 복사해 -DownloadUrl 로 주세요."
}

if ($DownloadUrl -notmatch 'download\.jbe') {
    Write-Warning "첨부 링크가 아닌 것 같습니다. 게시글 주소가 아니라 파일 링크를 복사했는지 확인하세요."
}

$marker = "[업데이트정보]id=$AppId|앱=$AppName|버전=$Version|다운로드=$DownloadUrl|서명=$signature"

Write-Host ""
Write-Host "버전      : $Version"
Write-Host "서명 파일 : $SignaturePath"
Write-Host "서명 대상 : $signedFile"
Write-Host ""

if ($signedFile -and ($signedFile -notmatch [regex]::Escape($Version))) {
    Write-Warning "서명 대상 파일 이름에 $Version 이 없습니다."
    Write-Warning "게시판에 올린 ZIP 속 exe와 다른 파일의 서명일 수 있습니다. 확인하세요."
    Write-Host ""
}
Write-Host "아래 한 줄을 게시글 본문에 붙여 넣으세요. (서식 없이 한 줄로)"
Write-Host "----------------------------------------------------------------"
Write-Host $marker
Write-Host "----------------------------------------------------------------"
Write-Host ""
Write-Host "첨부를 다시 올리면 링크가 바뀌므로, 표식도 함께 고쳐야 합니다."
Write-Host ""

# 바로 붙여 넣을 수 있게 클립보드에도 넣는다.
try {
    Set-Clipboard -Value $marker
    Write-Host "클립보드에 복사했습니다."
} catch {
    Write-Host "클립보드 복사는 실패했습니다. 위 줄을 직접 복사하세요."
}
