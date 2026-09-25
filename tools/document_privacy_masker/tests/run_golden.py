"""정답 샘플로 '문서 개인정보 마스킹' 찾기 규칙을 점검한다.

    python tests/run_golden.py            # 결과 요약
    python tests/run_golden.py --verbose  # 샘플마다 찾은 것 전부

실패 기준
  - 법정 7종(주민·외국인등록·카드·휴대전화·계좌·여권·운전면허)을 하나라도 놓치면 실패
  - 'forbid' 에 적은 글자를 개인정보로 잡으면 실패(공문 번호·부서명·날짜·금액 등)
  - 그 밖의 종류를 놓친 것은 '놓침'으로 세어 알려 준다(역시 0 이어야 통과)
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dpm_detect  # noqa: E402
from dpm_kinds import FIXED_CODES, label_of  # noqa: E402


def main() -> int:
    verbose = "--verbose" in sys.argv
    data = json.loads((HERE / "golden_cases.json").read_text(encoding="utf-8"))
    missed, forbidden, total = [], [], Counter()
    hit = Counter()

    for case in data["texts"]:
        text = case["text"]
        found = dpm_detect.detect_text(text)
        if verbose:
            print(f"\n[{case['id']}]")
            for f in found:
                print(f"   {f.label:8} {f.text!r:40} {f.confidence:.2f}  {' / '.join(f.reasons)}")
        for kind, value in case["expect"]:
            total[kind] += 1
            pos = text.find(value)
            ok = any(f.kind == kind and f.start <= pos and pos + len(value) <= f.end for f in found)
            if ok:
                hit[kind] += 1
            else:
                missed.append((case["id"], kind, value))
        for value in case["forbid"]:
            pos = text.find(value)
            if any(f.start < pos + len(value) and pos < f.end for f in found):
                forbidden.append((case["id"], value))

    for case in data["tables"]:
        cells = dpm_detect.detect_table(case["rows"])
        if verbose:
            print(f"\n[표] {case['id']}")
            for cf in cells:
                f = cf.finding
                print(f"   ({cf.row},{cf.col}) {f.label:8} {f.text!r:30} {' / '.join(f.reasons)}")
        for r, c, kind in case["expect"]:
            total[kind] += 1
            if any(cf.row == r and cf.col == c and cf.finding.kind == kind for cf in cells):
                hit[kind] += 1
            else:
                missed.append((case["id"], kind, case["rows"][r][c]))
        for r, c in case["forbid"]:
            if any(cf.row == r and cf.col == c for cf in cells):
                forbidden.append((case["id"], case["rows"][r][c]))

    print("\n종류별 찾은 비율")
    for kind in sorted(total, key=lambda k: (k not in FIXED_CODES, k)):
        mark = "법정" if kind in FIXED_CODES else "    "
        print(f"  {mark} {label_of(kind):8} {hit[kind]}/{total[kind]}")
    if missed:
        print("\n놓친 것")
        for cid, kind, value in missed:
            print(f"  - [{cid}] {label_of(kind)}: {value}")
    if forbidden:
        print("\n개인정보가 아닌데 잡은 것")
        for cid, value in forbidden:
            print(f"  - [{cid}] {value}")
    ok = not missed and not forbidden
    print("\n결과:", "통과" if ok else "실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
