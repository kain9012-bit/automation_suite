# 문서 개인정보 마스킹 — 가져온 코드와 참고한 자료

## 그대로 넣은 코드

| 이름 | 위치 | 라이선스 | 버전 |
|---|---|---|---|
| ko-pii (Marker Inc Korea) | `vendor/ko_pii/` | MIT (`vendor/ko_pii/LICENSE`) | 1.16.0, 커밋 9516cabd (2026-09-09) |

- 출처: https://github.com/Marker-Inc-Korea/ko-pii
- 고치지 않고 그대로 넣었다. 업데이트할 때는 폴더를 통째로 바꾸고 `tests/run_golden.py` 를 다시 돌린다.
- 외부 라이브러리를 쓰지 않는다(파이썬 표준 라이브러리만). 설치본 사이드카에 따로 넣을 것이 없다.

## 참고한 공개 도구 (제작자 사용 허락, 2026-09)

| 도구 | 출처 | 가져온 것 |
|---|---|---|
| safeDoc | gitlab.aigov.go.kr/dksrlrhkd/safeDoc, gitlab.aigov.go.kr/Ubermensch/safeDoc | 신뢰도 점수 방식, 주소 규칙, hwpx 다시 쓰기 방식 |
| KID | gitlab.aigov.go.kr/chanili2/KID | 표 머리글로 열 판단, 한자 병기 이름, 관계어 단서, 법정 7종 비공개 고정, 검수 흐름 |
| K-PoliShield | gitlab.aigov.go.kr/dltjrwns/k-polishield | 패턴·마스킹 엔진 구성 |
| Tiny PDF Editor (MIT) | gitlab.aigov.go.kr/soonpyo/tiny-pdf-editor | PDF 글자 실제 삭제(apply_redactions) 방식 |
| 00MASKING | gitlab.aigov.go.kr/00AI/00 | 미리보기에서 영역을 끌어 보강하는 화면 흐름 |

## 이 도구 파일

- `dpm_hancom.py`  옛 한글(hwp)을 설치된 한글로 hwpx 임시 사본으로 바꿈(늦은 바인딩, 사본 만든 뒤 지움)
- `document_privacy_masker_service.py` 앱이 부르는 입구(analyze_file → apply_file).
  확인 화면은 `app_analyze`·`app_page`·`app_apply` 를 부른다(bridge/extra_tools.py 에는 이 세 함수를 부르는 등록만 있다).
  화면 파일: `src/components/DocumentPrivacyMaskerPanel.tsx`, `src/components/document-privacy-masker.css`
- `dpm_kinds.py`  개인정보 종류·기본 처리 방식·법정 7종
- `dpm_detect.py` 찾기(ko-pii + 인사 서류 보강 규칙 + 표 머리글)
- `dpm_mask.py`   가린 글자 만들기
- `dpm_items.py`  문서 형식과 상관없는 항목 합치기·글자 단위 수정 계획·다시 검사
- `dpm_hwpx.py`   한글(hwpx) 읽기·쓰기(XML 글자만 바꿔 끼움, 미리보기·문서정보 정리)
- `dpm_pdf.py`    PDF 읽기·쓰기(PyMuPDF 실제 삭제, 표 선·그림 보존, 문서정보 정리)
- `tests/`        정답 샘플(`golden_cases.json`)·가림 모양·문서 끝까지 점검. `fixtures/` 는 모두 가짜 값

점검 방법(도구 폴더에서):

    python tests/run_golden.py
    python tests/run_mask.py
    python tests/run_documents.py      # PyMuPDF 필요
    python tests/run_app.py            # 확인 화면이 보내는 모양 그대로 (PyMuPDF 필요)

다른 도구와 모듈 이름이 겹치지 않도록 내부 모듈 이름은 모두 `dpm_` 으로 시작한다.
