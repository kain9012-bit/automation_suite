"""가리는 모양 점검: python tests/run_mask.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dpm_mask import masked_text  # noqa: E402

CASES = [
    ("PERSON", "김철수", "mask_part", "김*수"),
    ("PERSON", "김철수(金哲洙)", "mask_part", "김*수(***)"),
    ("PERSON", "남궁민수", "mask_part", "남**수"),
    ("PERSON", "이준", "mask_part", "이*"),
    ("MOBILE", "010-1234-5678", "mask_part", "010-****-5678"),
    ("MOBILE", "010 2345 6789", "mask_part", "010 **** 6789"),
    ("MOBILE", "01012345678", "mask_part", "010****5678"),
    ("PHONE", "063-239-3114", "mask_part", "063-***-3114"),
    ("EMAIL", "jmk1234@jbedu.kr", "mask_part", "jm*****@jbedu.kr"),
    ("ADDRESS", "전북특별자치도 전주시 완산구 홍산로 111, 202동 1503호", "mask_part", "전북특별자치도 전주시 완산구 *** ***, **** *****"),
    ("RRN", "780302-1234564", "mask_all", "******-*******"),
    ("RRN", "780302-1234564", "mask_part", "780302-1******"),
    ("RRN", "780302-1234564", "keep", "780302-1234564"),      # 사람이 고르면 법정 7종도 그대로 둔다
    ("ACCOUNT", "302-1234-5678-91", "mask_part", "***-****-**78-91"),
    ("BIRTH", "1978.03.02", "mask_part", "1978.**.**"),
    ("VEHICLE", "12가3456", "mask_part", "12가****"),
    ("PERSON", "홍길동", "keep", "홍길동"),
]

bad = 0
for kind, text, action, want in CASES:
    got = masked_text(kind, text, action)
    ok = got == want
    bad += not ok
    print(f"{'  ' if ok else '✗ '}{kind:8} {action:9} {text!r:45} → {got!r}" + ("" if ok else f"   (기대: {want!r})"))
print("\n결과:", "통과" if not bad else f"실패 {bad}건")
sys.exit(1 if bad else 0)
