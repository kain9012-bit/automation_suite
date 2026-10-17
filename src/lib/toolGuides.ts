/**
 * 파이썬 도구 사용가이드 단계. 화면 위에서 아래 순서로 적는다.
 * target 은 화면의 data-tour 표시. 화면에 없는 영역(저장 위치가 없는 도구 등)의 단계는 안내를 열 때 빠진다.
 *
 * 공통 화면(NativeToolPanel)을 쓰는 도구는 영역마다 설명만 적는다:
 *   tool-input 처리 대상 선택 · tool-options 작업 설정 · tool-output 저장 위치 · tool-confirm 원본 변경 확인 ·
 *   tool-run 실행 버튼 · tool-log 작업 기록
 * 자기 화면이 있는 도구(엑셀 분할·병합, PDF 페이지 정리, 문서 개인정보 마스킹)는 단계를 통째로 적는다.
 * 설명은 개조식(명사형으로 끝, 마침표 없음)으로 쓰고, 항목이 여럿이면 \n 으로 나눈다(카드에 · 항목으로 한 줄씩 나온다).
 */
export type GuideStep = { target: string; title: string; body: string };

type PanelText = Partial<Record<PanelTarget, string | [title: string, body: string]>>;
type PanelTarget = "tool-input" | "tool-options" | "tool-output" | "tool-confirm" | "tool-run" | "tool-log";

const PANEL_ORDER: PanelTarget[] = ["tool-input", "tool-options", "tool-output", "tool-confirm", "tool-run", "tool-log"];
const PANEL_TITLES: Record<PanelTarget, string> = {
  "tool-input": "처리 대상 선택",
  "tool-options": "작업 설정",
  "tool-output": "저장 위치",
  "tool-confirm": "원본 변경 확인",
  "tool-run": "실행",
  "tool-log": "작업 기록",
};

const PANEL_TEXTS: Record<string, PanelText> = {
  certificate_pdf_collector: {
    "tool-input": "취합할 이수증 PDF 선택(여러 개 가능)",
    "tool-output": "결과 엑셀 저장 위치 지정\n비워 두면 첫 번째 파일 폴더에 저장",
    "tool-run": "‘작업 실행’ → 이수증 정보를 읽어 엑셀 한 파일로 정리",
    "tool-log": "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시",
  },
  certificate_pdf_renamer: {
    "tool-input": "이름을 바꿀 한 장짜리 이수증 PDF 선택\n여러 장이 묶인 PDF는 ‘이수증 PDF 자동 분리’로 먼저 나누기",
    "tool-options": "새 이름에 쓸 항목을 쉼표로 구분해 입력\n항목 사이에 넣을 구분자 지정",
    "tool-confirm": "원본 PDF 이름을 바로 바꾸는 작업\n표시해야 실행 가능",
    "tool-run": "‘작업 실행’ → 이수증 정보로 파일 이름 변경\n바꾼 내역은 엑셀로 남김",
    "tool-log": "진행 상황과 결과 표시",
  },
  certificate_pdf_splitter: {
    "tool-input": "여러 장의 이수증이 묶인 PDF 선택",
    "tool-options": "나눈 파일 이름에 쓸 항목을 쉼표로 구분해 입력\n항목 사이에 넣을 구분자 지정",
    "tool-output": "나눈 파일을 둘 폴더 지정\n비워 두면 첫 번째 파일 폴더에 새 폴더를 만들어 저장",
    "tool-run": "‘작업 실행’ → 한 장씩 나눠 이수증 정보로 이름 붙이기",
    "tool-log": "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시",
  },
  empty_folder_cleaner: {
    "tool-input": "빈 폴더를 정리할 기준 폴더 선택",
    "tool-options": "표시하면 기준 폴더도 비어 있을 때 함께 삭제",
    "tool-confirm": "휴지통을 거치지 않고 바로 지우는 작업\n표시해야 실행 가능",
    "tool-run": "‘작업 실행’ → 안에 있는 빈 폴더 모두 삭제",
    "tool-log": "진행 상황과 결과 표시",
  },
  file_inventory: {
    "tool-input": "현황표를 만들 폴더 선택",
    "tool-options": "하위 폴더 포함 여부, 넣을 대상(파일·폴더), 확장자 필터 지정",
    "tool-output": "결과 엑셀 저장 위치 지정\n비워 두면 고른 폴더 안에 저장",
    "tool-run": "‘작업 실행’ → 파일·폴더 목록을 엑셀로 만들기",
    "tool-log": "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시",
  },
  folder_unpacker: {
    "tool-input": "파일을 꺼낼 폴더 선택\n안의 파일은 그 폴더의 바로 위 폴더로 이동",
    "tool-options": "하위 폴더 속 파일까지 꺼낼지, 파일 이름 앞에 폴더명을 붙일지 지정",
    "tool-confirm": "원본 파일을 옮기는 작업\n표시해야 실행 가능",
    "tool-run": "‘작업 실행’ → 파일을 위 폴더로 옮기고 빈 폴더 삭제",
    "tool-log": "진행 상황과 결과 표시",
  },
  homepage_post_collector: {
    "tool-options": "게시판 목록 주소 입력 후 ‘주소 확인’\n모을 페이지 범위, 본문·첨부파일 포함 여부 지정",
    "tool-output": "결과 저장 폴더 지정\n비워 두면 다운로드 폴더에 저장",
    "tool-run": "‘작업 실행’ → 게시글을 모아 엑셀로 저장\n‘중지’하면 그때까지 모은 것만 저장",
    "tool-log": "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시",
  },
  hwp_collector: {
    "tool-input": "합칠 한글 파일 선택\n목록 위에서부터 차례로 합침(끌어서 순서 변경)",
    "tool-output": "합친 파일 저장 위치 지정\n비워 두면 첫 번째 파일 폴더에 저장",
    "tool-run": "‘작업 실행’ → 한글 프로그램으로 한 문서로 합치기",
    "tool-log": "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시",
  },
  hwp_compress: {
    "tool-input": "용량을 줄일 한글 파일 선택\n파일마다 크기 표시",
    "tool-options": "압축 방식 선택\n목표 방식은 ‘목표 용량(MB)’에 맞춰 그림 축소",
    "tool-output": "저장 폴더 지정\n비워 두면 원본 폴더에 hwpx로 저장",
    "tool-run": "‘작업 실행’ → 그림을 줄여 저장\n끝나면 줄이기 전후 용량 표시",
    "tool-log": "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시",
  },
  hwp_to_hwpx_converter: {
    "tool-input": "바꿀 .hwp 파일이나 폴더 넣기",
    "tool-options": "하위 폴더까지 찾을지, 변환 중 한글 창을 보일지 지정",
    "tool-confirm": "변환에 성공하면 원본 .hwp 파일을 지우는 작업\n표시해야 실행 가능",
    "tool-run": "‘작업 실행’ → 원본과 같은 폴더에 .hwpx로 저장",
    "tool-log": "진행 상황과 결과 표시",
  },
  hwp_to_pdf_converter: {
    "tool-input": "PDF로 바꿀 한글 파일 선택",
    "tool-output": "PDF 저장 폴더 지정\n비워 두면 첫 번째 파일 폴더에 저장",
    "tool-run": "‘작업 실행’ → 한글 프로그램으로 파일마다 PDF 만들기",
    "tool-log": "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시",
  },
  multi_format_pdf_combiner: {
    "tool-input": "합칠 파일 선택(PDF·이미지·한글·워드·PPT)\n목록 위에서부터 차례로 합침(끌어서 순서 변경)",
    "tool-output": "합친 PDF 저장 위치 지정\n비워 두면 첫 번째 파일 폴더에 저장",
    "tool-run": "‘작업 실행’ → 파일마다 PDF로 바꿔 하나로 합치기",
    "tool-log": "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시",
  },
  pdf_compress: {
    "tool-input": "용량을 줄일 PDF 선택\n파일마다 크기 표시",
    "tool-options": "목표 방식과 ‘목표 용량(MB)’ 지정\n사진 위주로 줄여서 글자 위주 파일은 많이 줄지 않음",
    "tool-output": "저장 폴더 지정\n비워 두면 원본 폴더에 저장",
    "tool-run": "‘작업 실행’ → 압축\n끝나면 줄어든 용량 표시",
    "tool-log": "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시",
  },
  pdf_page_number_adder: {
    "tool-input": "페이지 번호를 넣을 PDF 하나 선택",
    "tool-options": "번호 형식, 시작 페이지·번호, 표시 위치, 글자 크기 지정",
    "tool-output": "저장 위치 지정\n비워 두면 원본 폴더에 ‘원본이름_페이지번호.pdf’로 저장",
    "tool-run": "‘작업 실행’ → 번호를 넣은 새 PDF 만들기",
    "tool-log": "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시",
  },
  rename_files: {
    "tool-input": "이름을 바꿀 파일 선택",
    "tool-options": "변경 방식(바꾸기·앞에 붙이기·뒤에 붙이기) 선택 후 문자열 입력\n확장자는 그대로",
    "tool-confirm": "원본 파일 이름을 바로 바꾸는 작업\n표시해야 실행 가능",
    "tool-run": "‘작업 실행’ → 이름 변경\n같은 이름이 이미 있으면 건너뜀",
    "tool-log": "진행 상황과 결과 표시",
  },
  zip_batch_extractor: {
    "tool-input": "풀 ZIP 파일이나 ZIP이 든 폴더 넣기",
    "tool-options": "압축파일 이름 폴더를 만들지, 시스템 파일을 뺄지 지정\n암호가 있으면 ‘압축 비밀번호’에 입력",
    "tool-output": "풀 곳 지정\n비워 두면 ZIP이 있는 폴더에 풀기",
    "tool-run": "‘작업 실행’ → ZIP을 차례로 풀기",
    "tool-log": "진행 상황과 결과 표시",
  },
};

const CUSTOM_STEPS: Record<string, GuideStep[]> = {
  document_privacy_masker: [
    { target: "mask-files", title: "가릴 문서", body: "한글·PDF 문서 넣기 → 개인정보로 보이는 곳을 찾아 아래에 표시\n곳마다 가릴지 선택, 빠진 것은 직접 추가" },
    { target: "mask-output", title: "저장 폴더와 확인", body: "가린 사본 저장 폴더 지정(비우면 원본 폴더)\n파일을 넣으면 나오는 확인 칸에 표시해야 실행 가능" },
    { target: "mask-run", title: "실행", body: "‘가린 사본 만들기’ → 사본 생성 후 가린 글자가 남았는지 검사\n원본은 그대로" },
    { target: "mask-log", title: "작업 기록", body: "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시" },
  ],
  excel_merge: [
    { target: "merge-files", title: "병합할 파일", body: "합칠 엑셀 파일 넣기\n넣은 뒤 아래에서 뺄 시트 체크 해제" },
    { target: "merge-modes", title: "병합 방식", body: "파일마다 시트로 모을지, 표를 아래로 이어 붙일지 선택" },
    { target: "merge-options", title: "추가 설정", body: "숨긴 시트 포함 여부, 원본 파일명·시트명 열 추가 여부 지정" },
    { target: "merge-output", title: "저장 폴더", body: "결과 파일 저장 폴더 지정\n비워 두면 첫 번째 파일 폴더에 저장" },
    { target: "merge-run", title: "실행", body: "‘병합 실행’ → 결과 파일 만들기" },
    { target: "merge-log", title: "작업 기록", body: "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시" },
  ],
  excel_split: [
    { target: "split-input", title: "처리 대상 선택", body: "나눌 엑셀 파일 하나 넣기" },
    { target: "split-reload", title: "다시 읽기", body: "넣은 파일을 엑셀에서 고쳤다면 눌러서 다시 읽기" },
    { target: "split-modes", title: "나누는 방식", body: "나누는 방식 선택(시트별·행 개수·특정 열 값)" },
    { target: "split-fields", title: "대상 시트와 항목명 줄", body: "나눌 시트와 항목명(칸 이름) 줄 지정\n방식에 따라 필요한 칸 추가 표시" },
    { target: "split-output", title: "저장 폴더", body: "나눈 파일을 둘 폴더 지정\n비워 두면 원본 옆에 ‘(파일명)_분할’ 폴더 생성" },
    { target: "split-preview", title: "미리보기", body: "파일을 넣으면 앞쪽 내용 표시\n항목명 줄이 맞는지 확인" },
    { target: "split-run", title: "실행", body: "‘분할 실행’ → 정한 방식대로 파일 나누기" },
    { target: "split-log", title: "작업 기록", body: "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시" },
  ],
  pdf_page_organizer: [
    { target: "organize-pages", title: "페이지 편집", body: "PDF를 넣으면 페이지를 그림으로 표시\n끌어서 순서 변경, 회전·삭제 가능" },
    { target: "organize-modes", title: "저장 방식", body: "한 파일로 저장할지, 몇 쪽씩 또는 한 쪽씩 나눠 저장할지 선택" },
    { target: "organize-selected", title: "고른 페이지만 저장", body: "표시하면 고른 페이지만 저장" },
    { target: "organize-output", title: "저장 폴더", body: "저장 폴더 지정\n비워 두면 맨 앞 페이지가 있던 PDF 폴더에 저장" },
    { target: "organize-run", title: "실행", body: "‘PDF 저장’ → 화면의 순서·회전대로 새 PDF 만들기" },
    { target: "organize-log", title: "작업 기록", body: "진행 상황과 결과 표시\n끝나면 ‘결과 폴더 열기’ 버튼 표시" },
  ],
};

export function toolGuideSteps(toolId: string): GuideStep[] {
  if (CUSTOM_STEPS[toolId]) return CUSTOM_STEPS[toolId];
  const texts = PANEL_TEXTS[toolId];
  if (!texts) return [];
  return PANEL_ORDER.flatMap((target) => {
    const text = texts[target];
    if (!text) return [];
    const [title, body] = typeof text === "string" ? [PANEL_TITLES[target], text] : text;
    return [{ target, title, body }];
  });
}
