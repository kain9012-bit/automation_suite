# AGENTS.md

## 프로젝트 개요

이 프로젝트는 PySide6 기반의 Windows 데스크톱 통합 업무 자동화 도구입니다.

- 메인 실행 진입점: `main.py`
- 핵심 앱 프레임워크: `app/`
- 개별 도구: `tools/`
- 사용자 설정/상태: `shared/config/`
- PyInstaller 빌드 설정: `automation_suite_onedir.spec`
- onedir 빌드 스크립트: `build_onedir.bat`

Codex는 이 프로젝트를 수정할 때 기존 통합 앱 구조와 개별 도구 구조를 최대한 보존해야 합니다.

## 기본 작업 원칙

1. 기존 기능을 임의로 삭제하지 않는다.
2. 사용자가 요청하지 않은 UI 구조 변경을 하지 않는다.
3. 변경 전에는 반드시 변경 계획을 먼저 설명한다.
4. 변경 범위는 사용자 요청과 직접 관련된 파일로 제한한다.
5. 빌드 산출물(`build/`, `dist/`)은 사용자가 명시적으로 요청하지 않는 한 수정 대상으로 삼지 않는다.
6. 깨진 인코딩 문자열이나 기존 문구는 요청 없이 대규모로 정리하지 않는다. 필요한 경우 별도 변경으로 제안한다.

## 탭 구조 유지

다음 상위 탭 구조는 프로젝트의 기본 정보 구조이므로 유지한다.

- 홈
- 엑셀·데이터
- PDF·문서
- 수집·추출
- 업무 자동화
- 한글·보고서
- 설정

도구 추가, 정렬, 이름 변경, 탭 이동을 할 때도 위 구조를 기준으로 한다. 사용자가 명확히 요청하지 않는 한 탭을 삭제하거나 병합하거나 전면 재배치하지 않는다.

## 도구 구조 규칙

각 도구는 `tools/<tool_id>/manifest.json`을 통해 등록된다.

`manifest.json`에는 가능한 한 다음 정보를 명확히 유지한다.

- `id`
- `name`
- `top_tab`
- `type`
- `entry`
- `description`
- `order`
- `enabled`
- `version`
- `keywords`

매니페스트는 반드시 유효한 JSON이어야 한다. JSON 문자열 따옴표, 쉼표, 한글 인코딩이 깨지지 않도록 주의한다.

## HTML 도구 규칙

HTML 도구는 가능하면 기존 방식처럼 단일 파일 구조를 유지한다.

- 기본 진입점: `tools/<tool_id>/web/index.html`
- 가능하면 HTML, CSS, JavaScript를 `index.html` 안에 inline으로 둔다.
- 사용자가 요청하지 않는 한 별도의 번들러, 프론트엔드 프레임워크, 패키지 매니저를 도입하지 않는다.
- 외부 CDN 의존성은 꼭 필요한 경우에만 추가하고, 오프라인 실행 가능성이 필요한 도구에서는 피한다.
- 기존 HTML 도구의 레이아웃, 카드형 영역, 버튼 스타일, 다운로드 방식과 최대한 일관되게 구현한다.

## Python 도구 규칙

Python 내부 도구는 `internal_python` 타입을 사용하며, entry 파일에서 `build_page()`를 제공해야 한다.

권장 구조:

- `tools/<tool_id>/<tool_id>_entry.py`: PySide6 UI 구성 및 `build_page()` 제공
- `tools/<tool_id>/<tool_id>_service.py`: 실제 파일 처리, 변환, 계산 등 비즈니스 로직

Python 도구 UI는 HTML 도구와 유사하게 다음 스타일을 유지한다.

- 카드형 작업 패널
- 가운데 중심 작업 영역
- 명확한 입력 영역과 실행 버튼
- 결과/로그 표시 영역
- 기존 앱의 흰색 배경, 부드러운 테두리, 업무용 UI 톤

사용자가 요청하지 않는 한 독립 실행형 창 구조로 바꾸지 않는다.

## 메인 앱 구조 규칙

다음 파일의 역할을 보존한다.

- `main.py`: 앱 시작, QApplication 생성, 스타일 로드, MainWindow 실행
- `app/main_window.py`: 메인 윈도우, 탭, 홈, 설정, 즐겨찾기, 최근 도구 관리
- `app/registry.py`: `tools/*/manifest.json` 기반 도구 등록
- `app/router.py`: 도구 타입별 페이지 생성
- `app/models.py`: 도구 매니페스트 모델
- `app/user_state.py`: 사용자 상태 저장/로드
- `app/ui/html_tool_page.py`: HTML 도구 표시
- `app/ui/exe_tool_page.py`: 외부 실행 파일 도구 실행
- `app/ui/home_page.py`: 홈 화면 및 바로가기
- `app/ui/settings_page.py`: 설정 화면

공통 구조를 바꾸는 수정은 영향 범위가 크므로, 반드시 사전에 이유와 영향을 설명한다.

## 빌드 규칙

PyInstaller 빌드는 onefile과 onedir 여부를 명확히 구분한다.

현재 기본 빌드 구조는 onedir 방식이다.

- onedir spec: `automation_suite_onedir.spec`
- onedir build script: `build_onedir.bat`
- 출력 폴더: `dist/automation_suite/`

빌드 관련 안내를 작성할 때는 다음을 구분한다.

- onedir: 실행 파일과 `_internal` 리소스 폴더가 함께 배포되는 방식
- onefile: 단일 exe로 묶는 방식

사용자가 onefile 빌드를 요청하지 않았다면 기존 onedir 빌드 방식을 기준으로 설명한다.

## 작업 전 보고 규칙

수정 전에 다음을 먼저 설명한다.

- 수정하려는 파일
- 수정 목적
- 예상 변경 내용
- 기존 기능에 대한 영향
- 실행 또는 빌드 확인 계획

큰 변경일수록 단계별로 나누어 설명한다.

## 작업 후 보고 규칙

수정 후에는 다음을 정리한다.

- 변경 파일 목록
- 각 파일의 변경 이유
- 주요 변경 내용
- 실행 방법
- 빌드 방법
- 테스트 또는 확인 결과
- 확인하지 못한 사항이 있으면 그 이유

실행 방법 예시:

```powershell
python main.py
```

onedir 빌드 방법 예시:

```powershell
.\build_onedir.bat
```

또는 직접 실행:

```powershell
py -3.12 -m PyInstaller --noconfirm automation_suite_onedir.spec
```

## 금지 사항

- 요청 없이 기존 도구를 삭제하지 않는다.
- 요청 없이 탭 구조를 변경하지 않는다.
- 요청 없이 UI를 전면 재설계하지 않는다.
- 요청 없이 HTML 단일 파일 도구를 다중 파일/프레임워크 구조로 바꾸지 않는다.
- 요청 없이 PyInstaller 빌드 방식을 onefile로 변경하지 않는다.
- 요청 없이 `build/`, `dist/`, `__pycache__/` 산출물을 편집하지 않는다.
- 요청 없이 사용자 설정 파일을 초기화하거나 삭제하지 않는다.
