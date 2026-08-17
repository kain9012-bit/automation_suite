import { extraToolSchemas } from "./toolSchemasExtras";

export interface Choice {
  label: string;
  value: string;
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
  /**
   * 칸 옆에 붙는 확인 버튼. 값을 검사한 결과를 작업 기록에 남기고,
   * 돌려받은 `fill`로 다른 칸을 채운다.
   */
  action?: FieldAction;
}

export interface ToolUiSchema {
  inputMode: "file" | "folder" | "none";
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
    extensions: ["pdf", "hwp", "hwpx", "doc", "docx", "ppt", "pptx"],
    inputLabel: "통합할 파일을 선택하세요",
    orderable: true,
    outputLabel: "통합 PDF 파일",
    outputExtension: "pdf",
  },
  pdf_compress: {
    extensions: ["pdf"],
    outputLabel: "압축 PDF 파일",
    outputExtension: "pdf",
    fields: [
      {
        key: "max_tries",
        label: "압축 시도 횟수",
        type: "number",
        defaultValue: 18,
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

