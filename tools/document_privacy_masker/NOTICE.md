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

- `dpm_kinds.py`  개인정보 종류·기본 처리 방식·법정 7종
- `dpm_detect.py` 찾기(ko-pii + 인사 서류 보강 규칙 + 표 머리글)
- `dpm_mask.py`   가린 글자 만들기
- `tests/`        정답 샘플(`golden_cases.json`, 모두 가짜 값)과 점검 스크립트

다른 도구와 모듈 이름이 겹치지 않도록 내부 모듈 이름은 모두 `dpm_` 으로 시작한다.
