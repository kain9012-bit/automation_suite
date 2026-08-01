# JB업무ON

**반복 업무를 간단하게 만드는 전북교육 업무도구 모음**

전북특별자치도교육청 업무에 쓰이는 도구를 한 프로그램에 모은 Windows 데스크톱 앱입니다.
엑셀·데이터, PDF·문서, 수집·추출, 업무 자동화, 간단 도구로 나뉘어 있고, 도구를 고르면
별도 창 없이 앱 안에서 바로 실행됩니다.

## 기술 구조

- **Tauri 2 + React 19 + TypeScript** — 화면과 앱 셸
- **Rust** — 도구 레지스트리, 서명 검증, 업데이트, 트레이
- **Python sidecar** — PDF·한글·엑셀 처리 로직 (사용자 PC에 Python 설치 불필요)
- **NSIS** — 단일 설치 파일 배포

## 폴더 구조

| 경로 | 역할 |
|---|---|
| `src/` | React 화면, 도구 검색, 즐겨찾기, 빠른 실행 데크 |
| `src-tauri/` | Rust 백엔드 — 도구 등록, HTML 로더, 업데이트, 트레이 |
| `tools/<도구ID>/` | 도구 한 개당 폴더 하나. `manifest.json`으로 등록 |
| `bridge/` | 공용 Python sidecar |
| `scripts/` | 설치본 빌드, 도구 패키징, 카탈로그 서명 |

기본 도구와 `%LOCALAPPDATA%\kr.go.jbe.automation-suite\tools`의 사용자 도구를 함께 읽습니다.
같은 ID가 있으면 더 높은 버전을 사용하므로 앱 전체를 다시 설치하지 않아도 도구만 교체할 수 있습니다.

## 개발 실행

```powershell
pnpm.cmd install
pnpm.cmd tauri dev
```

## 설치 파일 빌드

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

결과물은 `src-tauri\target\release\bundle\nsis`에 생성됩니다.

## 도구 추가

1. `tools\<도구ID>\manifest.json` 작성 (`id`, `name`, `top_tab`, `type`, `entry`, `description`, `order`, `enabled`, `keywords`)
2. HTML 도구는 `web\index.html`, Python 도구는 `bridge`에 핸들러 추가
3. 앱 실행 후 설정 → 도구 레지스트리 새로고침

Python 도구는 `bridge/extra_tools.py`(또는 `runner.py`)의 핸들러 표에 등록하고,
`src/lib/toolSchemasExtras.ts`에 입력 화면 스키마를 함께 넣어야 화면이 만들어집니다.

### 새 Python 라이브러리가 필요할 때

도구가 기존에 없던 라이브러리를 쓰면 sidecar를 다시 만들어야 합니다.

1. `bridge/requirements.txt`에 라이브러리 추가
2. **`bridge/runner.spec`의 `hiddenimports`에도 추가** — 이걸 빠뜨리면 빌드는
   성공하는데 실행할 때 `ModuleNotFoundError`가 납니다. PyInstaller가
   동적 import를 못 찾기 때문이며, 지금 spec에 pandas·openpyxl·bs4가
   일일이 나열된 이유이기도 합니다.
3. 버전을 올리고 태그를 밀면 GitHub Actions가 sidecar를 새로 빌드해
   설치본에 넣습니다. 사용자 앱은 자동 업데이트로 받아갑니다.

라이브러리가 아주 무거워서(수십 MB 이상) 모든 사용자가 받는 설치본에 넣기
부담스러우면, 그 도구만 별도 EXE로 빌드해 `manifest.json`의 `type`을 `exe`로
등록하는 방법도 있습니다. 본체 용량이 늘지 않는 대신 도구별 실행 파일을
따로 관리해야 합니다.

자세한 구조와 자동 업데이트 설정은 [TAURI_MIGRATION.md](TAURI_MIGRATION.md),
배포 절차는 [RELEASE.md](RELEASE.md)를 참고하세요.
