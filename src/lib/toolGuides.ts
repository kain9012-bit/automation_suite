/**
 * 파이썬 도구 사용가이드 단계. 화면 위에서 아래 순서로 적는다.
 * target 은 화면의 data-tour 표시. 화면에 없는 영역(저장 위치가 없는 도구 등)의 단계는 안내를 열 때 빠진다.
 *
 * 공통 화면(NativeToolPanel)을 쓰는 도구는 영역마다 설명만 적는다:
 *   tool-input 처리 대상 선택 · tool-options 작업 설정 · tool-output 저장 위치 · tool-confirm 원본 변경 확인 ·
 *   tool-run 실행 버튼 · tool-log 작업 기록
 * 자기 화면이 있는 도구(엑셀 분할·병합, PDF 페이지 정리, 문서 개인정보 마스킹)는 단계를 통째로 적는다.
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
    "tool-input": "취합할 이수증 PDF를 고릅니다. 여러 개를 한꺼번에 넣을 수 있습니다.",
    "tool-output": "결과 엑셀을 저장할 곳입니다. 비워 두면 첫 번째 파일이 있는 폴더에 저장합니다.",
    "tool-run": "‘작업 실행’을 누르면 이수증 정보를 읽어 엑셀 한 파일로 정리합니다.",
    "tool-log": "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다.",
  },
  certificate_pdf_renamer: {
    "tool-input": "이름을 바꿀 한 장짜리 이수증 PDF를 고릅니다. 여러 장이 묶인 PDF는 ‘이수증 PDF 자동 분리’로 먼저 나눕니다.",
    "tool-options": "새 이름에 쓸 항목을 쉼표로 구분해 적고, 항목 사이에 넣을 구분자를 정합니다.",
    "tool-confirm": "원본 PDF의 이름을 바로 바꾸는 작업이라, 표시해야 실행할 수 있습니다.",
    "tool-run": "‘작업 실행’을 누르면 이수증 정보로 파일 이름을 바꿉니다. 바꾼 내역은 엑셀로 남습니다.",
    "tool-log": "진행 상황과 결과가 적힙니다.",
  },
  certificate_pdf_splitter: {
    "tool-input": "여러 장의 이수증이 묶인 PDF를 고릅니다.",
    "tool-options": "나눈 파일의 이름에 쓸 항목을 쉼표로 구분해 적고, 구분자를 정합니다.",
    "tool-output": "나눈 파일을 둘 폴더입니다. 비워 두면 첫 번째 파일이 있는 폴더에 새 폴더를 만듭니다.",
    "tool-run": "‘작업 실행’을 누르면 한 장씩 나눠 이수증 정보로 이름을 붙입니다.",
    "tool-log": "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다.",
  },
  empty_folder_cleaner: {
    "tool-input": "빈 폴더를 정리할 기준 폴더를 고릅니다.",
    "tool-options": "표시하면 기준 폴더도 비어 있을 때 함께 지웁니다.",
    "tool-confirm": "폴더를 휴지통을 거치지 않고 바로 지우는 작업이라, 표시해야 실행할 수 있습니다.",
    "tool-run": "‘작업 실행’을 누르면 안에 있는 빈 폴더를 모두 지웁니다.",
    "tool-log": "진행 상황과 결과가 적힙니다.",
  },
  file_inventory: {
    "tool-input": "현황표를 만들 폴더를 고릅니다.",
    "tool-options": "하위 폴더 포함 여부, 파일·폴더 중 넣을 대상, 확장자 필터를 정합니다.",
    "tool-output": "결과 엑셀을 저장할 곳입니다. 비워 두면 고른 폴더 안에 저장합니다.",
    "tool-run": "‘작업 실행’을 누르면 파일·폴더 목록을 엑셀로 만듭니다.",
    "tool-log": "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다.",
  },
  folder_unpacker: {
    "tool-input": "파일을 꺼낼 폴더를 고릅니다. 안의 파일이 그 폴더의 바로 위 폴더로 옮겨집니다.",
    "tool-options": "하위 폴더 속 파일까지 꺼낼지, 파일 이름 앞에 폴더명을 붙일지 정합니다.",
    "tool-confirm": "원본 파일을 옮기는 작업이라, 표시해야 실행할 수 있습니다.",
    "tool-run": "‘작업 실행’을 누르면 파일을 위 폴더로 옮기고 빈 폴더는 지웁니다.",
    "tool-log": "진행 상황과 결과가 적힙니다.",
  },
  homepage_post_collector: {
    "tool-options": "게시판 목록 주소를 넣고 ‘주소 확인’을 누릅니다. 모을 페이지 범위와 본문·첨부파일 포함 여부를 정합니다.",
    "tool-output": "결과를 저장할 폴더입니다. 비워 두면 다운로드 폴더에 저장합니다.",
    "tool-run": "‘작업 실행’을 누르면 게시글을 모아 엑셀로 저장합니다. ‘중지’하면 그때까지 모은 것을 저장합니다.",
    "tool-log": "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다.",
  },
  hwp_collector: {
    "tool-input": "합칠 한글 파일을 고릅니다. 목록 위에서부터 차례로 합치며, 끌어서 순서를 바꿀 수 있습니다.",
    "tool-output": "합친 파일을 저장할 곳입니다. 비워 두면 첫 번째 파일이 있는 폴더에 저장합니다.",
    "tool-run": "‘작업 실행’을 누르면 한글 프로그램으로 파일들을 한 문서로 합칩니다.",
    "tool-log": "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다.",
  },
  hwp_compress: {
    "tool-input": "용량을 줄일 한글 파일을 고릅니다. 파일마다 크기가 표시됩니다.",
    "tool-options": "압축 방식을 고릅니다. 목표 방식이면 ‘목표 용량(MB)’에 맞춰 그림을 줄입니다.",
    "tool-output": "저장할 폴더입니다. 비워 두면 원본이 있는 폴더에 hwpx로 저장합니다.",
    "tool-run": "‘작업 실행’을 누르면 그림을 줄여 저장하고, 끝나면 줄이기 전후 용량을 보여 줍니다.",
    "tool-log": "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다.",
  },
  hwp_to_hwpx_converter: {
    "tool-input": "바꿀 .hwp 파일이나 폴더를 넣습니다.",
    "tool-options": "하위 폴더까지 찾을지, 변환 중 한글 창을 보일지 정합니다.",
    "tool-confirm": "변환에 성공하면 원본 .hwp 파일을 지우는 작업이라, 표시해야 실행할 수 있습니다.",
    "tool-run": "‘작업 실행’을 누르면 원본과 같은 폴더에 .hwpx로 저장합니다.",
    "tool-log": "진행 상황과 결과가 적힙니다.",
  },
  hwp_to_pdf_converter: {
    "tool-input": "PDF로 바꿀 한글 파일을 고릅니다.",
    "tool-output": "PDF를 저장할 폴더입니다. 비워 두면 첫 번째 파일이 있는 폴더에 저장합니다.",
    "tool-run": "‘작업 실행’을 누르면 한글 프로그램으로 파일마다 PDF를 만듭니다.",
    "tool-log": "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다.",
  },
  multi_format_pdf_combiner: {
    "tool-input": "합칠 파일(PDF·이미지·한글·워드·PPT)을 고릅니다. 목록 위에서부터 합치며, 끌어서 순서를 바꿀 수 있습니다.",
    "tool-output": "합친 PDF를 저장할 곳입니다. 비워 두면 첫 번째 파일이 있는 폴더에 저장합니다.",
    "tool-run": "‘작업 실행’을 누르면 파일마다 PDF로 바꿔 하나로 합칩니다.",
    "tool-log": "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다.",
  },
  pdf_compress: {
    "tool-input": "용량을 줄일 PDF를 고릅니다. 파일마다 크기가 표시됩니다.",
    "tool-options": "목표 방식과 ‘목표 용량(MB)’을 정합니다. 사진 위주로 줄이므로 글자 위주 파일은 많이 줄지 않습니다.",
    "tool-output": "저장할 폴더입니다. 비워 두면 원본이 있는 폴더에 저장합니다.",
    "tool-run": "‘작업 실행’을 누르면 압축하고, 끝나면 줄어든 용량을 보여 줍니다.",
    "tool-log": "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다.",
  },
  pdf_page_number_adder: {
    "tool-input": "페이지 번호를 넣을 PDF 하나를 고릅니다.",
    "tool-options": "번호 형식, 시작 페이지·번호, 표시 위치, 글자 크기를 정합니다.",
    "tool-output": "저장할 곳입니다. 비워 두면 원본과 같은 폴더에 ‘원본이름_페이지번호.pdf’로 저장합니다.",
    "tool-run": "‘작업 실행’을 누르면 번호를 넣은 새 PDF를 만듭니다.",
    "tool-log": "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다.",
  },
  rename_files: {
    "tool-input": "이름을 바꿀 파일을 고릅니다.",
    "tool-options": "변경 방식(바꾸기·앞에 붙이기·뒤에 붙이기)을 고르고 문자열을 적습니다. 확장자는 바뀌지 않습니다.",
    "tool-confirm": "원본 파일 이름을 바로 바꾸는 작업이라, 표시해야 실행할 수 있습니다.",
    "tool-run": "‘작업 실행’을 누르면 이름을 바꿉니다. 같은 이름이 이미 있는 파일은 건너뜁니다.",
    "tool-log": "진행 상황과 결과가 적힙니다.",
  },
  zip_batch_extractor: {
    "tool-input": "풀 ZIP 파일이나 ZIP이 든 폴더를 넣습니다.",
    "tool-options": "압축파일 이름의 폴더를 만들지, 시스템 파일을 뺄지 정합니다. 암호가 있으면 ‘압축 비밀번호’에 적습니다.",
    "tool-output": "풀 곳입니다. 비워 두면 ZIP이 있는 폴더에 풉니다.",
    "tool-run": "‘작업 실행’을 누르면 ZIP을 차례로 풉니다.",
    "tool-log": "진행 상황과 결과가 적힙니다.",
  },
};

const CUSTOM_STEPS: Record<string, GuideStep[]> = {
  document_privacy_masker: [
    { target: "mask-files", title: "가릴 문서", body: "한글·PDF 문서를 넣으면 개인정보로 보이는 곳을 찾아 아래에 보여 줍니다. 곳마다 가릴지 고르고, 빠진 것은 직접 추가합니다." },
    { target: "mask-output", title: "저장 폴더와 확인", body: "가린 사본을 저장할 폴더입니다(비우면 원본 폴더). 파일을 넣으면 나오는 확인 칸에 표시해야 사본을 만들 수 있습니다." },
    { target: "mask-run", title: "실행", body: "‘가린 사본 만들기’를 누르면 사본을 만들고, 가린 글자가 남지 않았는지 검사합니다. 원본은 바꾸지 않습니다." },
    { target: "mask-log", title: "작업 기록", body: "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다." },
  ],
  excel_merge: [
    { target: "merge-files", title: "병합할 파일", body: "합칠 엑셀 파일을 넣습니다. 넣으면 아래에서 넣지 않을 시트를 뺄 수 있습니다." },
    { target: "merge-modes", title: "병합 방식", body: "파일마다 시트로 모을지, 표를 아래로 이어 붙일지 고릅니다." },
    { target: "merge-options", title: "추가 설정", body: "숨긴 시트를 넣을지, 원본 파일명·시트명 열을 붙일지 정합니다." },
    { target: "merge-output", title: "저장 폴더", body: "결과 파일을 저장할 폴더입니다. 비워 두면 첫 번째 파일이 있는 폴더에 저장합니다." },
    { target: "merge-run", title: "실행", body: "‘병합 실행’을 누르면 결과 파일을 만듭니다." },
    { target: "merge-log", title: "작업 기록", body: "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다." },
  ],
  excel_split: [
    { target: "split-input", title: "처리 대상 선택", body: "나눌 엑셀 파일 하나를 넣습니다." },
    { target: "split-reload", title: "다시 읽기", body: "넣은 파일을 엑셀에서 고쳤다면 눌러서 다시 읽습니다." },
    { target: "split-modes", title: "나누는 방식", body: "시트별, 행 개수, 특정 열 값 중 나누는 방식을 고릅니다." },
    { target: "split-fields", title: "대상 시트와 항목명 줄", body: "나눌 시트와 항목명(칸 이름) 줄을 정합니다. 방식에 따라 필요한 칸이 더 나옵니다." },
    { target: "split-output", title: "저장 폴더", body: "나눈 파일을 둘 폴더입니다. 비워 두면 원본 옆에 ‘(파일명)_분할’ 폴더를 만듭니다." },
    { target: "split-preview", title: "미리보기", body: "파일을 넣으면 앞쪽 내용이 나옵니다. 항목명 줄이 맞는지 확인합니다." },
    { target: "split-run", title: "실행", body: "‘분할 실행’을 누르면 정한 방식대로 파일을 나눕니다." },
    { target: "split-log", title: "작업 기록", body: "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다." },
  ],
  pdf_page_organizer: [
    { target: "organize-pages", title: "페이지 편집", body: "PDF를 넣으면 페이지가 그림으로 나옵니다. 끌어서 순서를 바꾸고, 돌리거나 지울 수 있습니다." },
    { target: "organize-modes", title: "저장 방식", body: "한 파일로 저장할지, 몇 쪽씩 또는 한 쪽씩 나눠 저장할지 고릅니다." },
    { target: "organize-selected", title: "고른 페이지만 저장", body: "표시하면 고른 페이지만 저장합니다." },
    { target: "organize-output", title: "저장 폴더", body: "저장할 폴더입니다. 비워 두면 맨 앞 페이지가 있던 PDF와 같은 폴더에 저장합니다." },
    { target: "organize-run", title: "실행", body: "‘PDF 저장’을 누르면 화면의 순서와 회전대로 새 PDF를 만듭니다." },
    { target: "organize-log", title: "작업 기록", body: "진행 상황과 결과가 적힙니다. 끝나면 ‘결과 폴더 열기’로 결과가 있는 폴더를 엽니다." },
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
