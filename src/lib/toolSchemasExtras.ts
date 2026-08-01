import type { ToolUiSchema } from "./toolSchemas";

export const extraToolSchemas: Record<string, Partial<ToolUiSchema>> = {
  excel_merge: {
    inputLabel: "병합할 엑셀 파일을 선택하세요",
    multiple: true,
    extensions: ["xlsx", "xlsm", "csv"],
    outputMode: "file",
    outputLabel: "저장할 병합 파일",
    outputExtension: "xlsx",
    fields: [
      {
        key: "mode",
        label: "병합 방식",
        type: "select",
        defaultValue: "files_to_sheets",
        choices: [
          { label: "파일마다 시트로 모으기", value: "files_to_sheets" },
          { label: "모든 시트를 한 시트로 합치기", value: "workbook_sheets_to_one" },
          { label: "같은 이름 시트끼리 합치기", value: "same_sheets_together" },
        ],
      },
      { key: "add_source_file", label: "원본 파일명 열 추가", type: "checkbox", defaultValue: false },
      { key: "add_source_sheet", label: "원본 시트명 열 추가", type: "checkbox", defaultValue: false },
      { key: "include_hidden_sheets", label: "숨긴 시트도 포함", type: "checkbox", defaultValue: false },
    ],
  },
  certificate_pdf_splitter: {
    inputLabel: "분리할 이수증 PDF를 선택하세요",
    multiple: true,
    extensions: ["pdf"],
    outputMode: "folder",
    outputLabel: "분리 결과 저장 폴더",
    fields: [
      {
        key: "filename_fields",
        label: "파일명 항목",
        type: "text",
        defaultValue: "과정명,성명,근무기관",
        placeholder: "쉼표로 구분",
      },
      {
        key: "delimiter",
        label: "파일명 구분자",
        type: "text",
        defaultValue: "_",
      },
    ],
  },
  certificate_pdf_renamer: {
    inputLabel: "이름을 바꿀 이수증 PDF를 선택하세요",
    multiple: true,
    extensions: ["pdf"],
    outputMode: "hidden",
    destructive: true,
    fields: [
      {
        key: "filename_fields",
        label: "파일명 항목",
        type: "text",
        defaultValue: "과정명,성명,근무기관",
        placeholder: "쉼표로 구분",
      },
      {
        key: "delimiter",
        label: "파일명 구분자",
        type: "text",
        defaultValue: "_",
      },
    ],
  },
  empty_folder_cleaner: {
    inputMode: "folder",
    inputLabel: "빈 폴더를 정리할 기준 폴더를 선택하세요",
    multiple: false,
    outputMode: "hidden",
    destructive: true,
    fields: [
      {
        key: "include_root",
        label: "기준 폴더 자체도 비어 있으면 정리",
        type: "checkbox",
        defaultValue: false,
      },
    ],
  },
  homepage_post_collector: {
    inputMode: "none",
    inputLabel: "",
    multiple: false,
    outputMode: "folder",
    outputLabel: "결과 저장 폴더",
    fields: [
      {
        key: "board_url",
        label: "게시판 목록 URL",
        type: "text",
        placeholder: "https://www.jbe.go.kr/board/list.jbe?...",
      },
      {
        key: "start_page",
        label: "시작 페이지",
        type: "number",
        defaultValue: 1,
      },
      {
        key: "end_page",
        label: "끝 페이지",
        type: "number",
        defaultValue: 1,
      },
      {
        key: "max_posts",
        label: "최대 게시글 수(0=제한 없음)",
        type: "number",
        defaultValue: 0,
      },
      {
        key: "create_excel",
        label: "게시글 엑셀 만들기",
        type: "checkbox",
        defaultValue: true,
      },
      {
        key: "collect_body",
        label: "게시글 본문 포함",
        type: "checkbox",
        defaultValue: true,
      },
      {
        key: "download_files",
        label: "첨부파일도 내려받기",
        type: "checkbox",
        defaultValue: false,
      },
    ],
  },
};
