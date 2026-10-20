# 배포와 자동 업데이트

## 한눈에 보기

| 대상 | 방식 | 서명키 |
|---|---|---|
| 앱 본체 | 데이터 도구실 **'업무 도구 업데이트 이력'** 게시글의 `[업데이트정보]` 표식을 읽어 새 설치본(ZIP)을 받고, 압축을 푼 설치 파일의 서명을 확인한 뒤 설치 | `.signing/tauri.key` |
| 개별 도구 | 서명된 도구 카탈로그로 도구만 교체 — **지금은 꺼져 있음**(아래 참고) | `.signing/tools_ed25519.key` |

- 설치본은 **내 PC에서** `scripts/build_release.ps1`로 만들고 서명합니다.
- 앱은 **게시판만 봅니다.** 본청에서 GitHub 접속이 막혀 있어 업데이트를 게시글로 받도록 바꿨습니다.
  배경과 제약은 [docs/board-update.md](docs/board-update.md)에 정리했습니다.
- GitHub 저장소는 소스 보관용입니다. 앱 업데이트에는 쓰이지 않습니다.

| 게시글 | 주소 | 하는 일 |
|---|---|---|
| JB업무ON 배포 게시글 | `dataSid=1162415` | 설치본 ZIP 첨부, 사용자 안내 |
| 업무 도구 업데이트 이력 | `dataSid=1151988` (`update-config.json`의 `app.post_url`) | 버전별 변경 내용, 앱이 읽는 `[업데이트정보]` 표식 |

---

## 처음 한 번만 하는 준비

- **서명키를 보관합니다.** `.signing\tauri.key`, `.signing\tauri.password`가 있어야 설치본에 서명할 수 있습니다.
  개인키는 저장소에 올라가지 않습니다(`.gitignore`로 제외). **잃어버리면 이미 설치된 앱에 업데이트를 내려줄 수 없으니**
  별도로 백업해 두세요. 앱에는 짝이 되는 공개키(`update-config.json`의 `app.public_key`)가 들어 있습니다.
- **빌드 환경** — Visual Studio 2022 Build Tools, Rust, Node(pnpm), Python과 `bridge\requirements.txt`의 라이브러리.
  `build_release.ps1`이 시작할 때 빠진 것을 확인해 알려 줍니다.

---

## 새 버전 배포하기

### 0. 어떤 번호로 올릴지

기본은 **맨 뒤 숫자만 올린다.** 대부분의 수정이 여기에 해당한다.

| 상황 | 예시 |
|---|---|
| 오류 수정, 문구·색상 조정, 옵션 추가 등 대부분 | 1.2.1 → **1.2.2** |
| 도구가 새로 생기거나 화면 구조가 바뀔 때 | 1.2.9 → **1.3.0** |
| 쓰던 방식이 통째로 달라져 사용자가 다시 익혀야 할 때 | 1.9.0 → **2.0.0** |

**번호는 절대 되돌릴 수 없다.** 자동 업데이트는 더 높은 번호일 때만 동작하므로,
1.3.0을 배포한 뒤 1.2.5를 올려도 아무에게도 전달되지 않는다.

### 1. 버전 올리고 업데이트 내용 적기

버전이 네 곳(`package.json`, `tauri.conf.json`, `Cargo.toml`, `Cargo.lock`)에 흩어져 있어
하나만 빠뜨리면 자동 업데이트가 조용히 동작하지 않습니다. 스크립트로 한 번에 맞춥니다.

```powershell
cd C:\work\automation_suite
powershell -ExecutionPolicy Bypass -File .\scripts\set_version.ps1 1.4.9
```

바뀐 내용은 `src/lib/releaseNotes.ts`에 적습니다. 업데이트 뒤 처음 켰을 때 위쪽 띠와 설정의
**업데이트 내역**에 그대로 나오고, 게시판 '업무 도구 업데이트 이력' 글에도 같은 내용을 씁니다.

### 2. 설치본 만들기

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

스크립트가 하는 일:

1. Python sidecar를 PyInstaller로 새로 빌드(`-SkipSidecar`로 건너뛸 수 있음)하고 `--selftest`로 확인
2. 프론트엔드 빌드 후 NSIS 설치본 빌드
3. `.signing\tauri.key`로 서명해 `.sig` 파일 생성

결과는 `src-tauri\target\release\bundle\nsis`에 `JB업무ON_<버전>_x64-setup.exe`와 `.exe.sig`로 생깁니다.

### 3. ZIP으로 묶기

게시판이 exe 첨부를 받지 않으므로 설치본을 ZIP으로 감쌉니다. ZIP은 운반 수단일 뿐이고,
앱은 **압축을 푼 exe의 서명**을 확인합니다. ZIP 안에는 설치 파일 하나만 넣습니다.

```powershell
$v = "1.4.9"
$nsis = ".\src-tauri\target\release\bundle\nsis"
Compress-Archive -LiteralPath "$nsis\JB업무ON_${v}_x64-setup.exe" -DestinationPath "$nsis\JB업무ON_${v}_x64-setup.zip" -Force
```

### 4. 배포 게시글에 ZIP 올리기

JB업무ON 배포 게시글(`dataSid=1162415`)을 고쳐 새 ZIP을 첨부하고 저장합니다.
저장한 뒤 첨부 링크를 우클릭해 **링크 주소를 복사**합니다(`download.jbe?…&fileSid=NNNNNN`).
첨부를 다시 올리면 `fileSid`가 바뀌므로 매번 새로 복사합니다.

배포 게시글 본문의 **프로그램 내려받기** 버튼 주소도 같은 링크로 바꾸고, 도구 수가 바뀌었으면 함께 고칩니다.

### 5. 표식 한 줄 만들기

서명은 448자짜리 base64라 손으로 옮겨 적으면 거의 틀립니다. 한 글자만 어긋나도 설치가 거부되므로
스크립트로 만듭니다. 버전은 `package.json`, 서명은 빌드 결과에서 읽고, 만든 줄은 클립보드에도 들어갑니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\print_board_marker.ps1 `
    -DownloadUrl "https://www.jbe.go.kr/board/download.jbe?...&fileSid=NNNNNN"
```

화면에 나오는 **서명 대상** 파일 이름이 올린 ZIP 속 exe와 같은지 확인합니다.

### 6. 업데이트 이력 게시글 고치기

'업무 도구 업데이트 이력' 글(`dataSid=1151988`)을 고칩니다.

- **프로그램 자동 확인용 정보**의 `[업데이트정보]id=JBEDT-0005…` 줄을 5번에서 만든 줄로 통째로 바꿉니다.
  **서식 없이 한 줄로** 넣습니다. 중간에 태그가 끼면 거기서 잘립니다.
- 맨 위에 새 버전 카드를 넣고(1번에서 적은 내용), 이전 카드의 강조 표시를 옮깁니다.
- 상단 기간과 맨 아래 **업데이트 기준일**을 고치고, 1개월이 지난 카드는 뺍니다.

### 7. 확인

이미 설치된 앱은 시작 1.8초 뒤 게시글을 읽어 새 버전을 확인합니다. 설정 화면의 **지금 확인**으로 바로 확인할 수도 있습니다.
새 버전이 있으면 받아 두고 화면 위쪽에 **지금 적용**을 띄웁니다. 적용 시점은 사용자가 고릅니다.

처음 바꾼 배포 방식이거나 표식을 손봤다면 아래를 확인합니다.

1. 표식에 앱보다 낮은 버전을 적으면 → 아무 일도 없어야 한다
2. 높은 버전이면 → 받아 두었다는 안내가 떠야 한다
3. `서명` 값을 한 글자 고치면 → 검증에 막혀 설치가 시작되지 않아야 한다 **(가장 중요)**

### 8. 소스 올리기

```powershell
git add -A
git commit -m "1.4.9: …"
git push
```

---

## GitHub Actions (필요할 때만)

`.github/workflows/release.yml`은 `v`로 시작하는 태그를 밀면 설치본을 만들어 GitHub Releases에 올립니다.
**앱 업데이트는 게시판만 보므로 이 경로는 배포에 필요하지 않습니다.** 쓰려면 저장소 **Settings → Secrets and variables → Actions**에
`TAURI_SIGNING_PRIVATE_KEY`(`.signing\tauri.key` 내용 전체)와 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`(`.signing\tauri.password` 내용)를
등록해야 합니다.

---

## 도구만 따로 업데이트하기 (지금은 쓰지 않음)

> **현재 이 기능은 꺼져 있습니다.** `update-config.json`의 `tools.catalog_url`이
> 비어 있어 앱이 카탈로그를 확인하지 않습니다. 의도한 상태입니다.
>
> 도구는 설치본 안에 함께 들어가므로, 도구를 고치거나 새로 추가해도
> 앱 업데이트만으로 전부 따라옵니다. 이 경로는 그 위에 얹는 선택 사항이고,
> 얻는 것은 다운로드 용량 절약뿐인데 서명키와 배포 절차가 하나 더 늘어납니다.
>
> 나중에 필요해지면 아래 절차를 마치고 주소를 채우면 그때 켜집니다. Rust 쪽 구현은 이미 되어 있습니다.

앱 본체를 건드리지 않고 도구를 추가하거나 교체하는 경로입니다.

### 1. 도구 패키지 만들기

```powershell
py -3.12 scripts\package_tool.py tools\qr_code_generator --base-url https://<올릴 주소>/tools
```

`tool-packages\` 아래에 ZIP과 카탈로그 항목이 만들어집니다.

### 2. 카탈로그 서명하기

여러 도구 항목을 모아 아래 형태의 JSON을 만든 뒤 서명합니다.

```json
{
  "schema_version": 1,
  "tools": [
    {
      "id": "qr_code_generator",
      "name": "QR 코드 생성",
      "version": "1.2.0",
      "url": "https://.../qr_code_generator-1.2.0.zip",
      "sha256": "…",
      "size": 12345
    }
  ]
}
```

```powershell
py -3.12 scripts\sign_tool_catalog.py tool-catalog.json --output tool-catalog.signed.json
```

### 3. 올리고 주소 연결하기

서명된 카탈로그와 ZIP을 공개 주소에 올린 뒤, `update-config.json`의 `tools.catalog_url`에 카탈로그 주소를 적습니다.
본청 망에서도 받으려면 GitHub이 아닌 곳에 올려야 합니다.

앱은 시작할 때 카탈로그 서명을 검증하고, 처음 보는 ID는 자동 설치,
이미 있는 ID는 더 높은 버전일 때만 교체합니다. ZIP 내부 경로, 패키지 ID·버전,
SHA-256을 모두 확인하므로 중간에 바뀐 파일은 설치되지 않습니다.

---

## 알아두면 좋은 것

- **코드 서명 인증서가 없습니다.** 설치할 때 Windows SmartScreen 경고가 뜹니다.
  사용자는 `추가 정보 → 실행`을 눌러야 합니다. 상용 인증서를 사거나
  기관 인증서를 받아야 없앨 수 있습니다.
- **버전은 되돌릴 수 없습니다.** 업데이트는 더 높은 버전일 때만 동작하므로,
  1.1.0을 배포한 뒤 1.0.9를 올려도 아무도 받지 않습니다.
- **게시글을 못 읽으면 조용히 넘어갑니다.** 업데이트가 안 될 뿐 앱은 그대로 동작합니다.
- **sidecar는 저장소에 없습니다.** 수십 MB라 `.gitignore`로 빼 두었고,
  `build_release.ps1`이 빌드할 때마다 새로 만듭니다.
