import { extraToolSchemas } from "./toolSchemasExtras";

export interface Choice {
  label: string;
  value: string;
  /** 카드 모양 선택지 아래에 붙는 짧은 설명. */
  hint?: string;
}

export interface FieldAction {
  label: string;
  /** 부를 보조 동작. `도구ID__동작` 형태를 쓴다. */
  tool: string;
  /** 이 칸의 값을 어떤 이름으로 보낼지. */
  payloadKey: string;
}

export interface ToolField {
  key: string;
  label: string;
  type: "text" | "number" | "select" | "checkbox";
  defaultValue?: string | number | boolean;
  placeholder?: string;
  choices?: Choice[];
  /** "cards": 드롭다운 대신 선택지를 모두 펼쳐 카드로 보여 준다. 어떤 방식이 있는지 한눈에 보이게. */
  appearance?: "cards";
  /**
   * 칸 옆에 붙는 확인 버튼. 값을 검사한 결과를 작업 기록에 남기고,
   * 돌려받은 `fill`로 다른 칸을 채운다.
   */
  action?: FieldAction;
  /** 다른 칸(key)의 값이 values 중 하나일 때 이 칸을 비활성화한다. 값은 그대로 두고 입력만 막는다. */
  disabledWhen?: { key: string; values: string[] };
}

export interface ToolUiSchema {
  /** "both": 파일과 폴더를 모두 받는다(폴더를 넣으면 도구가 안에서 찾는다). */
  inputMode: "file" | "folder" | "both" | "none";
  inputLabel: string;
  multiple: boolean;
  extensions?: string[];
  outputMode: "file" | "folder" | "hidden";
  outputLabel?: string;
  outputExtension?: string;
  fields?: ToolField[];
  destructive?: boolean;
  /**
   * 합치는 순서가 결과를 바꾸는 도구. 목록에서 순서를 바꾸고 한 줄씩 뺄 수 있고,
   * 파일을 다시 고르면 교체가 아니라 뒤에 덧붙인다.
   */
  orderable?: boolean;
  /** 실행 중에 중지할 수 있는 도구. 하던 항목까지 마치고 결과를 저장한 뒤 멈춘다. */
  cancellable?: boolean;
  /** 끝나면 결과를 팝업으로 크게 알리는 도구. 실패도 팝업으로 알린다. */
  resultPopup?: boolean;
  /** 넣은 파일마다 크기와 전체 합계를 보여 주는 도구. */
  showSizes?: boolean;
}

const defaultSchema: ToolUiSchema = {
  inputMode: "file",
  inputLabel: "처리할 파일을 선택하세요",
  multiple: true,
  outputMode: "file",
  outputLabel: "저장할 파일",
};

const schemas: Record<string, Partial<ToolUiSchema>> = {
  certificate_pdf_collector: {
    extensions: ["pdf"],
    outputLabel: "결과 엑셀 파일",
    outputExtension: "xlsx",
  },
  file_inventory: {
    inputMode: "folder",
    inputLabel: "현황표를 만들 폴더를 선택하세요",
    multiple: false,
    outputLabel: "결과 엑셀 파일",
    outputExtension: "xlsx",
    fields: [
      { key: "recursive", label: "하위 폴더 포함", type: "checkbox", defaultValue: true },
      {
        key: "target_mode",
        label: "포함 대상",
        type: "select",
        defaultValue: "파일+폴더",
        choices: [
          { label: "파일과 폴더", value: "파일+폴더" },
          { label: "파일만", value: "파일만" },
          { label: "폴더만", value: "폴더만" },
        ],
      },
      {
        key: "extensions",
        label: "확장자 필터",
        type: "text",
        placeholder: "예: pdf, xlsx, hwpx (비우면 전체)",
      },
      {
        key: "exclude_office_temp",
        label: "Office 임시 파일 제외",
        type: "checkbox",
        defaultValue: true,
      },
    ],
  },
  folder_unpacker: {
    inputMode: "folder",
    inputLabel: "파일을 꺼낼 폴더를 선택하세요",
    multiple: true,
    outputMode: "hidden",
    destructive: true,
    fields: [
      { key: "recursive", label: "하위 폴더 포함", type: "checkbox", defaultValue: true },
      {
        key: "prefix_folder",
        label: "파일명 앞에 폴더명 붙이기",
        type: "checkbox",
        defaultValue: false,
      },
    ],
  },
  hwp_collector: {
    extensions: ["hwp", "hwpx"],
    inputLabel: "취합할 한글 파일을 선택하세요",
    orderable: true,
    outputLabel: "취합할 한글 파일",
    outputExtension: "hwpx",
  },
  hwp_to_hwpx_converter: {
    inputMode: "both",
    extensions: ["hwp"],
    outputMode: "hidden",
    fields: [
      {
        key: "recursive",
        label: "폴더를 넣으면 하위 폴더까지 찾기",
        type: "checkbox",
        defaultValue: true,
      },
      {
        key: "visible",
        label: "한글 프로그램 처리 화면 표시",
        type: "checkbox",
        defaultValue: false,
      },
    ],
  },
  hwp_to_pdf_converter: {
    extensions: ["hwp", "hwpx"],
    outputMode: "folder",
    outputLabel: "PDF 저장 폴더",
  },
  multi_format_pdf_combiner: {
    // 처리부(ensure_pdf)는 이미지도 PDF로 바꿔 붙일 수 있는데 화면에서 막고 있었다.
    extensions: [
      "pdf",
      "png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff",
      "hwp", "hwpx", "doc", "docx", "ppt", "pptx",
    ],
    inputLabel: "통합할 파일을 선택하세요 (PDF·이미지·한글·워드·PPT)",
    orderable: true,
    outputLabel: "통합 PDF 파일",
    outputExtension: "pdf",
  },
  pdf_compress: {
    extensions: ["pdf"],
    cancellable: true,
    resultPopup: true,
    showSizes: true,
    // 파일마다: 비우면 원본 옆에 '이름_압축.pdf'. 전체 합계: 이 폴더 아래 새 폴더에 원래 이름으로.
    outputMode: "folder",
    outputLabel: "저장 폴더",
    fields: [
      {
        key: "target_mode",
        label: "목표 방식",
        type: "select",
        appearance: "cards",
        defaultValue: "each",
        choices: [
          {
            label: "파일마다 목표 용량 이하",
            value: "each",
            hint: "파일 하나하나를 목표 용량 이하로 줄입니다. 결과: 원본이름_압축.pdf",
          },
          {
            label: "전체 합계를 목표 용량 이하",
            value: "total",
            hint: "넣은 파일을 모두 합친 용량을 목표 이하로 맞춥니다. 새 폴더에 원래 이름으로 저장",
          },
        ],
      },
      {
        key: "target_mb",
        label: "목표 용량(MB)",
        type: "number",
        defaultValue: 5,
      },
    ],
  },
  pdf_page_number_adder: {
    multiple: false,
    extensions: ["pdf"],
    outputLabel: "번호가 추가된 PDF",
    outputExtension: "pdf",
    fields: [
      {
        key: "format_type",
        label: "번호 형식",
        type: "select",
        defaultValue: "숫자",
        choices: [
          { label: "숫자", value: "숫자" },
          { label: "- 숫자 -", value: "- 숫자 -" },
          { label: "숫자 / 전체", value: "숫자 / 전체" },
        ],
      },
      { key: "start_page", label: "시작 페이지", type: "number", defaultValue: 1 },
      { key: "start_number", label: "시작 번호", type: "number", defaultValue: 1 },
      {
        key: "position",
        label: "표시 위치",
        type: "select",
        defaultValue: "하단 가운데",
        choices: [
          { label: "하단 왼쪽", value: "하단 왼쪽" },
          { label: "하단 가운데", value: "하단 가운데" },
          { label: "하단 오른쪽", value: "하단 오른쪽" },
          { label: "상단 왼쪽", value: "상단 왼쪽" },
          { label: "상단 가운데", value: "상단 가운데" },
          { label: "상단 오른쪽", value: "상단 오른쪽" },
        ],
      },
      { key: "font_size", label: "글자 크기", type: "number", defaultValue: 10 },
    ],
  },
  rename_files: {
    inputLabel: "이름을 바꿀 파일을 선택하세요",
    outputMode: "hidden",
    destructive: true,
    fields: [
      {
        key: "mode",
        label: "변경 방식",
        type: "select",
        defaultValue: "replace",
        choices: [
          { label: "문자열 바꾸기", value: "replace" },
          { label: "앞에 붙이기", value: "prefix" },
          { label: "뒤에 붙이기", value: "suffix" },
        ],
      },
      { key: "before", label: "바꿀 문자열", type: "text" },
      { key: "after", label: "새 문자열", type: "text" },
    ],
  },
  zip_batch_extractor: {
    inputMode: "both",
    extensions: ["zip"],
    outputMode: "folder",
    outputLabel: "압축 해제 폴더(선택)",
    fields: [
      {
        key: "recursive",
        label: "폴더를 넣으면 하위 폴더까지 찾기",
        type: "checkbox",
        defaultValue: true,
      },
      {
        key: "extract_direct",
        label: "압축파일명 폴더 없이 바로 풀기",
        type: "checkbox",
        defaultValue: false,
      },
      {
        key: "exclude_junk",
        label: "불필요한 시스템 파일 제외",
        type: "checkbox",
        defaultValue: true,
      },
      { key: "password", label: "압축 비밀번호", type: "text" },
    ],
  },
};

export function getToolSchema(toolId: string): ToolUiSchema {
  return {
    ...defaultSchema,
    ...(schemas[toolId] ?? {}),
    ...(extraToolSchemas[toolId] ?? {}),
  };
}

export function initialToolOptions(schema: ToolUiSchema) {
  return Object.fromEntries(
    (schema.fields ?? []).map((field) => [
      field.key,
      field.defaultValue ?? (field.type === "checkbox" ? false : ""),
    ]),
  );
}

