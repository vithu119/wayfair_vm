export interface TemplateEntry {
  template_id: string
  filename: string
  category: string
  category_status: string
  template_purpose: string
  fill_status: string
  listing_sheet: string | null
  header_row: number | null
  safe_write_start_row: number | null
  is_active: boolean
  warnings: string[]
  blocking_reasons: string[]
  analysis_timestamp: string
  registration_timestamp: string
  profile?: Record<string, unknown>
}

export interface SourceFile {
  source_id: string
  filename: string
  row_count: number
  columns: string[]
  asin_column: string | null
  sku_column: string | null
  category_column: string | null
  preview: Record<string, string>[]
  sheet_names?: string[]
  chosen_sheet?: string
}

export interface AsinValidationItem {
  input: string
  normalized: string
  valid: boolean
  reason?: string
  duplicate: boolean
  parent_sku?: string | null
  sku?: string | null
}

export interface AsinValidation {
  items: AsinValidationItem[]
  valid_count: number
  invalid_count: number
  duplicate_count: number
}

export type RunStatus = 'created' | 'resolved' | 'validated' | 'exported'

export interface ResolvedProduct {
  asin: string
  sku: string | null
  product_name: string | null
  template_id: string | null
  template_filename: string | null
  source_id: string | null
  source_row: Record<string, string>
  status: 'matched' | 'unmatched' | 'ambiguous'
}

export interface Run {
  run_id: string
  status: RunStatus
  uploaded_templates: string[]
  source_files: string[]
  asins: string[]
  resolved_products: ResolvedProduct[]
  manual_edits: Record<string, string>
  validation_findings: ValidationFinding[]
  export_files: ExportFile[]
  created_at: string
  updated_at: string
}

export interface PreviewCell {
  value: string
  status: 'source_value' | 'missing' | 'unmapped' | 'fixed_value' | 'manual'
}

export interface PreviewRow {
  asin: string
  sku: string | null
  template_id: string
  cells: Record<string, PreviewCell>
}

export interface ValidationFinding {
  asin: string
  sku: string | null
  column: string
  value: string
  severity: 'blocking' | 'error' | 'warning' | 'review' | 'info'
  error_type: string
  recommended_action: string
}

export interface ExportFile {
  filename: string
  template_id: string
  file_type: 'xlsx' | 'csv'
  product_count: number
}

export interface DownloadFile {
  filename: string
  size_bytes: number
  template_id: string | null
  file_type: string
}
