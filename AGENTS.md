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
| `bridge/` | 공용 Python sidecar. `runner.py`, `extra_tools.py` |
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
- 내려받기는 `<a download href="blob:…|data:…">` 그대로 쓰면 된다. 앱 안(iframe)에서는 앱이 끼워 넣는 스크립트
  (`src/lib/htmlToolDownload.ts`)가 가로채 Rust `save_tool_download`로 '다운로드' 폴더에 저장한다.
  WebView2 의 내려받기에 기대지 않는다(1.4.4 전에는 앱 안에서 반응이 없던 일이 있었다).
- 앱 안에서는 CSP 때문에 blob 주소로 만든 Worker 가 막힌다. 생성은 되지만 오류만 내고 응답하지 않으므로,
  Worker 를 쓰면 먼저 응답을 확인하고 안 되면 화면에서 직접 처리하는 길을 둔다(예: `doc_size_reducer`).
- 앱 안에서는 파일 끌어다 놓기가 HTML 도구까지 오지 않는다(앱이 먼저 받는다). 파일은 '눌러서 고르기'로 받는다.
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

## 도구 카드 아이콘

- 아이콘은 `src/lib/toolIcons.ts`의 `TOOL_ICONS`에서 도구 ID로 정한다. 기능을 나타내는 lucide 아이콘만 쓴다.
- 색은 도구마다 정하지 않는다. 탭(`top_tab`)으로 정해진다(`TAB_STYLES`, `index.css`의 `tone-*`).
- **새 도구를 넣으면 `TOOL_ICONS`에 한 줄 추가한다.** 빠뜨리면 `tests/regression/frontend_helpers.test.ts`가 실패한다.
  (빠뜨린 채 배포돼도 탭 아이콘이 나오므로 화면이 깨지지는 않는다.)
- 새 탭을 만들면 `TAB_STYLES`와 `index.css`의 `tone-*` 색(밝은·어두운 화면 둘 다)을 함께 추가한다.

## 문서 검색(1.4.4~)

사이드바 '문서 검색'. Rust `src-tauri/src/docsearch/`, 화면 `src/components/DocSearchView.tsx`.
계획서는 Project 문서 `claude/1.4.4_문서검색_계획.md`.

- 색인은 SQLite(FTS5) 한 파일: `%LOCALAPPDATA%\kr.go.jbe.automation-suite\docsearch\index.db`.
- 한국어 낱말 나누기는 Lindera(mecab-ko-dic). **사전 압축 파일은 `src-tauri/vendor/lindera/2.3.4/`에 있고**,
  `src-tauri/.cargo/config.toml`의 `LINDERA_DICTIONARIES_PATH`로 빌드 때 인터넷 없이 쓴다.
  폴더 이름이 lindera 버전이라 `Cargo.toml`에서 `lindera = "=2.3.4"`로 못박았다. 올리면 폴더도 함께 바꾼다.
- 폴더를 계속 감시하지 않는다. 대조 시점은 ① 프로그램 켜지고 90초 뒤(검색 폴더를 골라 시작한 PC만)
  ② 문서 검색 화면을 열 때(마지막 대조 10분 경과) ③ [지금 다시 읽기]. 수정 날짜·크기만 비교한다.
- hwp·hwpx·docx·xlsx·pptx·txt 는 Rust 에서, PDF 는 사이드카 `runner.py --pdf-text-list`(PyMuPDF)로 읽는다.
- 배포용·암호 문서, 100MB 초과, 원드라이브 온라인 전용 파일은 이름으로만 찾는다.
- 건너뛰는 폴더: 시스템 폴더(`SKIP_DIRS`)와, 안에 `conda-meta`·`pyvenv.cfg`·`unins000.exe`·`uninstall.exe`가 있는
  프로그램 폴더(`PROGRAM_MARKERS`). 사용자가 검색 폴더로 직접 고른 폴더 자체는 따지지 않는다.
- 내용까지 읽을 문서 종류(1.4.5, `docsearch/types.rs`): meta `content_types`(쉼표로 이은 id).
  **표시가 없으면 모든 종류**(1.4.4 에서 만든 색인은 그대로), 처음 고를 때 기본은 한글·PDF·워드·텍스트.
  끈 종류는 다음 대조(`sync_list`)에서 글을 지우고 `name`(이름으로만 찾음), 켠 종류는 `pending`.
  종류를 바꾸면 하던 대조를 멈추고 다시 돈다(`index::restart`). 글을 지워도 index.db 크기는 바로 줄지 않는다(빈 자리를 다시 씀).
  종류 id·확장자는 `src/lib/docsearch.ts`의 `CONTENT_TYPES`와 같게 둔다.
- 검색 폴더 [×]는 확인 창(`plugin-dialog`의 `ask`, 권한 `dialog:allow-message`)을 거친다.
- 처음 열면 검색 폴더를 고르게 하고(meta `folders_confirmed`), 고르기 전에는 아무 파일도 읽지 않는다.
  고른 폴더는 화면 왼쪽 '검색 폴더'에 문서 수와 함께 늘 보인다. 읽는 중에는 아래쪽에 진행률과 [취소]
  (`docsearch_cancel`, 못 읽은 문서는 `pending`으로 남아 다음 대조 때 이어 읽음).
- 결과의 파일 아이콘은 그 PC 탐색기의 아이콘을 확장자별로 받아 쓴다(`docsearch/icons.rs`, 48px PNG).
  한컴·마이크로소프트 아이콘 그림을 프로그램에 넣어 배포하지 않는다. 못 받으면 원래 아이콘.
- [색인 정리](1.4.6, `docsearch_compact`): `index::exclusive` 로 대조·읽기를 멈추고 기다린 뒤 혼자
  `db::compact`(FTS optimize → VACUUM → WAL 비우기)를 한다. 끝나면 멈췄던 읽기·밀린 대조를 이어 한다.
  정리 중에는 다른 연결이 쓰기를 기다리므로 `migrate` 는 스키마 표시가 같으면 쓰지 않는다.
- 설치 제거 때 `docsearch` 색인 폴더를 지운다(`installer-hooks.nsh`의 `NSIS_HOOK_POSTUNINSTALL`).
  **업데이트 때는 절대 지우지 않는다**: `/UPDATE`(앱 자동 업데이트)와, 새 설치 파일이 이전 제거 프로그램을
  `_?=설치폴더`로 부를 때($EXEDIR = $INSTDIR)는 건너뛴다. 이 조건을 바꾸면 Wine 등으로 네 가지 경우를 다시 확인한다.

## HTML 도구의 외부 부품(1.4.6~)

HTML 도구가 `cdn.jsdelivr.net` 에서 받던 부품(xlsx·exceljs·pdf-lib·jszip·chart.js·datalabels)과
Pretendard 글꼴은 `tools/_vendor` 에 사본을 두고, `src-tauri/src/html_vendor.rs` 가 도구를 열 때
(앱 안·브라우저 모두) 그 자리에 끼워 넣는다. **도구 HTML 파일의 주소는 그대로 둔다.**
- 도구에 새 외부 부품을 쓰면 `html_vendor.rs` 의 `SCRIPTS` 표, `tools/_vendor`, `THIRD_PARTY_NOTICES.txt` 에 함께 더한다.
  안 하면 테스트 `every_bundled_html_tool_works_offline` 가 실패한다.
- 사본은 npm 에 올라온 그 버전의 배포 파일 그대로 쓴다(jsdelivr 가 주는 것과 같은지 확인함).
- 학사일정 추출의 나이스 Open API 호출처럼 도구 기능 자체가 인터넷을 쓰는 것은 그대로다.

## 처음 사용 안내(튜토리얼, 1.4.6~)

`src/components/TutorialOverlay.tsx`. jb_quickpanel 의 튜토리얼과 같은 방식이다.
- 단계마다 `view`(home·docsearch·settings)로 화면을 옮기고 `data-tour` 표시가 붙은 곳을 강조한다.
  화면을 고치다 `data-tour` 를 지우면 그 단계는 강조 없이 가운데 카드만 뜬다(2초 기다린 뒤).
- 어둡게 하는 것은 `.tutorial-spotlight` 의 바깥 그림자 하나뿐이다. 화면 전체에 어두운 막을 더 깔면
  강조한 곳까지 어두워진다(1.4.5까지의 문제).
- 안내 중에 도구를 실제로 열지 않는다('최근 사용'에 남기 때문). 마친 기록은 localStorage `jbedu-suite:tutorial-complete`.

## 빠른 실행(런처) 규칙

홈 화면의 `QuickLauncher`가 사이트·폴더·파일·프로그램 네 가지를 다룬다.
(명령·단축키·텍스트·대기·매크로는 제대로 동작하지 않아 1.4.3에서 뺐다. 저장값에 남은 것은 `quickDeck.ts`의 `readStoredDeck`이 지운다.)

- **모두 Rust에서 직접 실행한다**(`macro_deck.rs`의 `run_native`). Python sidecar를 쓰지 않는다.
  링크 하나 여는 데 sidecar를 띄우면 몇 초씩 걸리므로 이 경로를 유지한다.
- 전역 단축키 등록에 성공한 조합은 창 `keydown` 폴백에서 제외해 이중 실행을 막는다.

## 버전과 배포

버전은 네 곳에 있다. 하나라도 어긋나면 자동 업데이트가 조용히 동작하지 않는다.

`package.json`, `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml`, `src-tauri/Cargo.lock`

**직접 고치지 말고 `scripts/set_version.ps1`을 쓴다.** 태그를 밀면 GitHub Actions가
sidecar 빌드 → Rust 빌드 → 서명 → 릴리스 발행까지 처리한다.
자세한 절차는 `RELEASE.md`.

개발 실행은 `scripts/dev.ps1`, 로컬 설치본 빌드는 `scripts/build_release.ps1`.

게시판 자동 업데이트(`src-tauri/src/board_update.rs`):
- 켤 때 '업무 도구 업데이트 이력' 글(update-config.json `post_url`)을 열어 `JBEDT-0005` 표식을 읽는다(그 글 조회수 +1).
- 표식의 `다운로드=`는 **첨부 주소(download.jbe … fileSid=)**를 쓴다. 게시글 주소를 쓰면 새 버전이 있는 동안
  켤 때마다 JB업무ON 글 조회수가 오른다. 첨부를 다시 올리면 fileSid 가 바뀌므로 `버전=`·`서명=`과 함께 꼭 고친다
  (옛 주소로 받으면 'EOCD' 압축 오류).
- 받은 설치본은 캐시 `updates\JBEduON-<버전>-setup.exe`. 같은 버전이 있고 서명이 맞으면 다시 받지 않고(1.4.6),
  다른 버전 설치본과 설치를 마친 설치본은 지운다.

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
