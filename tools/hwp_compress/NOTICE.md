# 한글 용량 압축 — 참고한 코드

| 이름 | 출처 | 라이선스 | 기준 |
|---|---|---|---|
| HWPX 용량 줄이기 도우미 v1.0 | https://gitlab.aigov.go.kr/kimosed/hwpx-size-reduction-assistant | MIT (Copyright (c) 2026) | 커밋 afd7f92 (2026-08-30) |

- 원본은 C#(.NET Framework) 프로그램이다. 코드를 그대로 넣지 않고, 처리 규칙을 파이썬(Pillow)으로 옮겼다.
  - 압축 방식 4가지와 기준값(화질 우선 2560px·90, 용량 우선 1600px·78, 메일 첨부용 1920px·85·10MB, 목표 용량 1920px·85)
  - 목표 용량 단계(1920·85 → 1600·80 → 1440·75 → 1280·70), 목표에 닿으면 멈춤, 가장 작은 결과를 고름
  - 그대로 두는 그림(움직이는 GIF, 300KB 미만이면서 긴 변 1600px 미만, 기준 크기 이하인 PNG·BMP·GIF)
  - BinData 안의 jpg·jpeg·png·bmp·gif 만 줄이고 이름·형식은 그대로(본문 XML 을 바꾸지 않음)
  - 전자서명 항목이 있는 문서는 처리하지 않음, 결과를 다시 열어 항목 누락·그림 열림 확인
  - 결과 이름 '원본이름_용량축소.hwpx'
- 이 앱에서 더한 것: 옛 한글(hwp)은 설치된 한글로 임시 hwpx 를 만든 뒤 줄임(`hcz_hancom.py`), 암호가 걸린 문서 거르기,
  같은 이름이 있으면 '(1)' 붙이기(앱의 다른 도구와 같음), 중지, 결과 팝업.

## 이 도구 파일

- `hwp_compress_service.py` 처리 규칙과 앱이 부르는 입구(`compress_files`). 앱 연결은 `bridge/extra_tools.py` 의 `run_hwp_compress`.
- `hcz_hancom.py` 옛 한글(hwp) → hwpx 변환(늦은 바인딩, 보안 모듈, 한글 종료 보장). 다른 도구 코드를 불러 쓰지 않는다.
- 다른 도구와 모듈 이름이 겹치지 않도록 내부 모듈 이름은 `hcz_` 로 시작한다.
- 시험: `tests/regression/test_hwp_compress.py` (저장소 루트에서 실행)
