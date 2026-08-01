# AGENTS.md

## 프로젝트 개요

**JB업무ON** — 반복 업무를 간단하게 만드는 전북교육 업무도구 모음.

Tauri 2 + React 19 + Rust로 만든 Windows 데스크톱 앱입니다.
예전에는 PySide6 기반이었으나 현재는 Tauri 구조이며, 옛 PySide6 셸(`app/`, `main.py`)은
제거되었습니다. 오래된 문서나 코드를 근거로 PySide6 구조를 복원하지 마세요.

| 경로 | 역할 |
|---|---|
| `src/` | React 화면. 사이드바, 도구 그리드, 홈 빠른 실행, 설정 |
| `src-tauri/src/` | Rust 백엔드. `lib.rs`(도구 레지스트리·HTML 로더), `desktop.rs`(트레이·설정), `macro_deck.rs`(빠른 실행), `updates.rs`(도구 카탈로그) |
| `tools/<도구ID>/` | 도구 한 개당 폴더 하나. `manifest.json`으로 등록 |
| `bridge/` | 공용 Python sidecar. `runner.py`, `extra_tools.py`, `macro_actions.py` |
| `scripts/` | 빌드·배포·버전 스크립트 |
| `.github/workflows/` | 태그 푸시 시 설치본 빌드·서명·발행 |

## 기본 작업 원칙

1. 기존 기능을 임의로 삭제하지 않는다.
2. 사용자가 요청하지 않은 UI 구조 변경을 하지 않는다.
3. 변경 전에는 반드시 변경 계획을 먼저 설명한다.
4. 변경 범위는 사용자 요청과 직접 관련된 파일로 제한한다.
5. 빌드 산출물(`dist/`, `build/`, `src-tauri/target/`)은 요청 없이 건드리지 않는다.
6. 깨진 인코딩 문자열이나 기존 문구는 요청 없이 대규모로 정리하지 않는다.

## 탭 구조 유지

다음 상위 탭 구조는 프로젝트의 기본 정보 구조이므로 유지한다.

- 엑셀·데이터
- PDF·문서
- 수집·추출
- 업무 자동화
- 간단 도구

도구 추가, 정렬, 이름 변경, 탭 이동을 할 때도 위 구조를 기준으로 한다.
사용자가 명확히 요청하지 않는 한 탭을 삭제하거나 병합하지 않는다.

## 도구 구조 규칙

각 도구는 `tools/<tool_id>/manifest.json`으로 등록된다. 다음 항목을 유지한다.

`id`, `name`, `top_tab`, `type`, `entry`, `description`, `order`, `enabled`, `version`, `keywords`

`type`은 `html` 또는 `internal_python`이다. 매니페스트는 유효한 JSON이어야 하고
**BOM이 있으면 Rust가 조용히 도구를 건너뛴다.**

### HTML 도구

- 진입점: `tools/<tool_id>/web/index.html`
- HTML·CSS·JS를 `index.html` 안에 inline으로 둔다
- 요청 없이 번들러나 프레임워크를 도입하지 않는다
- 오프라인 실행이 필요한 도구에서는 외부 CDN을 피한다
- **API 키를 코드에 박지 않는다.** 저장소가 공개되어 있어 그대로 노출된다.
  키가 필요하면 사용자가 설정에서 입력하도록 만든다

### Python 도구

세 곳을 함께 갖춰야 화면이 만들어진다. 하나라도 빠지면 도구가 열리지 않는다.

1. `tools/<tool_id>/<tool_id>_service.py` — 실제 처리 로직
2. `bridge/extra_tools.py`(또는 `runner.py`)의 핸들러 표에 `tool_id` 등록
3. `src/lib/toolSchemasExtras.ts`에 입력 화면 스키마 추가

`web/index.html`이 남아 있어도 `type`이 `internal_python`이면 HTML로 열리지 않는다.
반대로 `type`이 `html`일 때만 `web/index.html` 폴백이 적용된다.

### 새 Python 라이브러리가 필요할 때

`bridge/requirements.txt`와 **`bridge/runner.spec`의 `hiddenimports` 양쪽에** 추가한다.
`hiddenimports`를 빠뜨리면 빌드는 성공하는데 실행할 때 `ModuleNotFoundError`가 난다.

## 빠른 실행(런처) 규칙

홈 화면의 `QuickLauncher`가 사이트·폴더·파일·프로그램·명령·단축키·텍스트·대기·매크로를 다룬다.

- **사이트·폴더·파일·프로그램·명령·대기는 Rust에서 직접 실행한다**(`macro_deck.rs`의 `run_native`).
  링크 하나 여는 데 Python sidecar를 띄우면 몇 초씩 걸리므로 이 경로를 유지한다.
- 키 입력이 필요한 **단축키·텍스트**만 sidecar(`bridge/macro_actions.py`)로 넘긴다.
- 전역 단축키 등록에 성공한 조합은 창 `keydown` 폴백에서 제외해 이중 실행을 막는다.

## 버전과 배포

버전은 네 곳에 있다. 하나라도 어긋나면 자동 업데이트가 조용히 동작하지 않는다.

`package.json`, `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml`, `src-tauri/Cargo.lock`

**직접 고치지 말고 `scripts/set_version.ps1`을 쓴다.** 태그를 밀면 GitHub Actions가
sidecar 빌드 → Rust 빌드 → 서명 → 릴리스 발행까지 처리한다.
자세한 절차는 `RELEASE.md`.

개발 실행은 `scripts/dev.ps1`, 로컬 설치본 빌드는 `scripts/build_release.ps1`.

## 작업 전후 보고 규칙

수정 전에는 수정할 파일, 목적, 예상 변경 내용, 기존 기능에 대한 영향, 확인 계획을 설명한다.
수정 후에는 변경 파일 목록, 각 파일의 변경 이유, 실행·빌드 방법, 확인 결과,
확인하지 못한 사항과 그 이유를 정리한다.

## 금지 사항

- 요청 없이 기존 도구를 삭제하지 않는다
- 요청 없이 탭 구조를 변경하거나 UI를 전면 재설계하지 않는다
- 요청 없이 HTML 단일 파일 도구를 다중 파일·프레임워크 구조로 바꾸지 않는다
- 요청 없이 `dist/`, `build/`, `src-tauri/target/` 산출물을 편집하지 않는다
- 요청 없이 사용자 설정 파일을 초기화하거나 삭제하지 않는다
- `.signing/`의 개인키를 저장소에 커밋하지 않는다
