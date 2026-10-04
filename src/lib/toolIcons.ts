import {
  ArrowRightLeft,
  Award,
  BadgeCheck,
  Calculator,
  CalendarDays,
  ChartColumn,
  ClipboardList,
  Cloud,
  Combine,
  Copy,
  Dices,
  Diff,
  EyeOff,
  FileOutput,
  FilePen,
  FileSpreadsheet,
  FileText,
  FolderOutput,
  FolderSearch,
  FolderX,
  Hash,
  LayoutGrid,
  Layers,
  Link2,
  ListChecks,
  Merge,
  Minimize2,
  Newspaper,
  PackageOpen,
  PencilLine,
  QrCode,
  School,
  Scissors,
  Sparkles,
  Split,
  Table2,
  TrendingUp,
  Users,
  WandSparkles,
  Workflow,
  type LucideIcon,
} from "lucide-react";

/**
 * 도구 카드 아이콘과 색을 한곳에서 정한다.
 *
 * - 색은 도구마다 정하지 않고 탭(top_tab)으로 정한다. 새 도구도 탭만 맞으면 색이 저절로 맞는다.
 * - 아이콘은 기능을 나타내는 것을 도구 ID 로 정한다. 모두 lucide 에서 골라 모양이 같다.
 * - 아이콘을 정하지 않은 도구는 탭 아이콘(사이드바와 같은 것)을 쓴다.
 *
 * 새 도구를 넣으면 TOOL_ICONS 에 한 줄 추가한다. 빠뜨리면 회귀 시험
 * (tests/regression/frontend_helpers.test.ts)이 알려 준다.
 */

export interface TabStyle {
  icon: LucideIcon;
  /** CSS 클래스 tone-<값> (index.css) */
  tone: string;
}

export const TAB_STYLES: Record<string, TabStyle> = {
  "엑셀·데이터": { icon: FileSpreadsheet, tone: "data" },
  "PDF·문서": { icon: FileText, tone: "doc" },
  "수집·추출": { icon: FolderSearch, tone: "collect" },
  "업무 자동화": { icon: Workflow, tone: "auto" },
  "간단 도구": { icon: Sparkles, tone: "simple" },
};

export const TOOL_ICONS: Record<string, LucideIcon> = {
  // PDF·문서
  multi_format_pdf_combiner: Combine,
  hwp_collector: Layers,
  hwp_to_pdf_converter: FileOutput,
  hwp_to_hwpx_converter: ArrowRightLeft,
  pdf_compress: Minimize2,
  hwp_compress: Minimize2,
  pdf_page_organizer: LayoutGrid,
  pdf_page_number_adder: Hash,
  certificate_pdf_collector: Award,
  certificate_pdf_splitter: Scissors,
  certificate_pdf_renamer: FilePen,
  document_privacy_masker: EyeOff,
  // 엑셀·데이터
  excel_merge: Merge,
  excel_split: Split,
  criteria_compare_matcher: Link2,
  data_duplicate_finder: Copy,
  data_normalizer: WandSparkles,
  excel_quality_checker: ListChecks,
  excel_stats_report: ChartColumn,
  id_number_validator: BadgeCheck,
  privacy_masker: EyeOff,
  reshape_unpivot: Table2,
  school_name_standardizer: School,
  school_year_compare: TrendingUp,
  // 수집·추출
  academic_schedule_extractor: CalendarDays,
  homepage_post_collector: Newspaper,
  // 업무 자동화
  rename_files: PencilLine,
  folder_unpacker: FolderOutput,
  file_inventory: ClipboardList,
  zip_batch_extractor: PackageOpen,
  empty_folder_cleaner: FolderX,
  gyeodetong_group_register: Users,
  k_edufine_group_register: Users,
  // 간단 도구
  simple_calculators: Calculator,
  simple_draw_tools: Dices,
  text_compare_tool: Diff,
  word_cloud_generator: Cloud,
  qr_code_generator: QrCode,
};

export function toolIcon(tool: { id: string; top_tab: string }): LucideIcon {
  return TOOL_ICONS[tool.id] ?? TAB_STYLES[tool.top_tab]?.icon ?? Sparkles;
}

export function toolTone(tool: { top_tab: string }): string {
  return TAB_STYLES[tool.top_tab]?.tone ?? "default";
}
