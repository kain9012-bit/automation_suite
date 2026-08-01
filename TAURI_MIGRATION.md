# JB업무ON Tauri 구조

**JB업무ON — 반복 업무를 간단하게 만드는 전북교육 업무도구 모음**

이 프로젝트는 기존 PySide6 셸을 Tauri 2 + React 19 + Rust 구조로 재구성한 버전입니다.
Docufinder의 코드를 복사하지 않고, 아이보리 배경·남색(#003264) 강조색·좁은 사이드바·
중앙 작업 카드·빠른 검색 같은 정보 구조와 화면 원리를 적용했습니다.

## 구성

- `src/`: React 화면, 도구 검색, 즐겨찾기, 최근 사용, 중앙 HTML/네이티브 작업 화면
- `src-tauri/`: Rust 도구 레지스트리, HTML 로더, Python sidecar, 서명 업데이트
- `tools/`: 한 도구당 하나의 `manifest.json`을 가진 도구 패키지
- `bridge/`: 기존 Python 서비스 로직을 UI와 분리해 실행하는 공통 sidecar
- `scripts/`: 설치본 빌드, 도구 패키징, 업데이트 서명 도구

기본 도구와 `%LOCALAPPDATA%\kr.go.jbe.automation-suite\tools`의 사용자 도구를
함께 읽습니다. 같은 ID가 있으면 더 높은 버전을 사용하므로 앱 전체를 다시 설치하지
않아도 도구만 교체할 수 있습니다.

## 개발 실행

```powershell
pnpm.cmd install
pnpm.cmd tauri dev
```

## 단일 설치 파일 빌드

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

결과 NSIS 설치 파일은 `src-tauri\target\release\bundle\nsis`에 생성됩니다.
Python sidecar는 설치 파일 안에 포함되므로 사용자 PC에 Python을 설치할 필요가 없습니다.

## 앱 자동 업데이트

`src-tauri/tauri.conf.json`의 updater endpoint를 실제 배포 주소로 바꿉니다.
업데이트 산출물은 `.signing\tauri.key`로 서명되며 앱에는 공개키만 들어갑니다.
개인키를 잃으면 기존 설치본에 업데이트를 제공할 수 없으므로 별도 보관이 필요합니다.

## 새 도구 자동 추가

1. `tools\<도구ID>\manifest.json`과 실행 파일을 준비합니다.
2. `scripts\package_tool.py`로 ZIP과 SHA-256 카탈로그 항목을 만듭니다.
3. 카탈로그 payload는 `schema_version: 1`과 `tools` 배열을 포함해야 합니다.
4. `scripts\sign_tool_catalog.py`로 카탈로그를 서명합니다.
5. `update-config.json`의 `catalog_url`을 서명 카탈로그 주소로 지정합니다.

앱은 시작 시 카탈로그 서명을 검증하고 새 ID는 자동 추가, 기존 ID는 더 높은 버전일 때
자동 업데이트합니다. ZIP 내부 경로, 패키지 ID·버전, SHA-256을 모두 검증합니다.

## 배포 전 반드시 바꿀 값

- `src-tauri/tauri.conf.json`의 `plugins.updater.endpoints`
- `update-config.json`의 `tools.catalog_url`

현재 이 두 주소는 배포 저장소가 정해지기 전의 자리표시자/빈 값입니다.
