import type { ToolUiSchema } from "./toolSchemas";

export const extraToolSchemas: Record<string, Partial<ToolUiSchema>> = {
  hwp_compress: {
    inputLabel: "용량을 줄일 한글 파일(hwp·hwpx)을 선택하세요",
    multiple: true,
    extensions: ["hwp", "hwpx"],
    cancellable: true,
    resultPopup: true,
    showSizes: true,
    // 기본·파일마다: 비우면 원본 옆에 '원본이름_용량축소.hwpx'. 전체 합계: 이 폴더 아래 새 폴더에 원래 이름으로.
    outputMode: "folder",
    outputLabel: "저장 폴더",
    outputPlaceholder: "비워 두면 원본과 같은 폴더에 저장합니다(전체 합계 방식은 첫 번째 파일이 있는 폴더에 새 폴더를 만듭니다).",
    fields: [
      {
        key: "target_mode",
        label: "압축 방식",
        type: "select",
        appearance: "cards",
        defaultValue: "basic",
        choices: [
          {
            label: "기본 줄이기",
            value: "basic",
            hint: "한글의 [그림 줄이기]처럼 잘라낸 영역을 지우고, 삽입한 크기에 맞춰 150dpi로 줄입니다. 결과: 원본이름_용량축소.hwpx",
          },
          {
            label: "파일마다 목표 용량 이하",
            value: "each",
            hint: "파일 하나하나를 목표 용량 이하로 줄입니다. 결과: 원본이름_용량축소.hwpx",
          },
          {
            label: "전체 합계를 목표 용량 이하",
            value: "total",
            hint: "넣은 파일을 모두 합친 용량을 목표 이하로 맞춥니다. 새 폴더에 원래 이름(.hwpx)으로 저장",
          },
        ],
      },
      {
        key: "target_mb",
        label: "목표 용량(MB)",
        type: "number",
        defaultValue: 5,
        disabledWhen: { key: "target_mode", values: ["basic"] },
      },
    ],
  },
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
    outputPlaceholder: "비워 두면 첫 번째 파일이 있는 폴더에 새 폴더를 만들어 저장합니다.",
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
    destructiveLabel: "빈 폴더가 휴지통을 거치지 않고 바로 삭제되는 작업임을 확인했습니다.",
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
    cancellable: true,
    outputMode: "folder",
    outputLabel: "결과 저장 폴더(비우면 다운로드 폴더)",
    outputPlaceholder: "비워 두면 다운로드 폴더에 저장합니다.",
    fields: [
      {
        key: "board_url",
        label: "게시판 목록 URL",
        type: "text",
        placeholder: "https://www.jbe.go.kr/board/list.jbe?...",
        action: {
          label: "주소 확인",
          tool: "homepage_post_collector__probe",
          payloadKey: "board_url",
        },
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
