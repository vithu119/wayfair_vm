import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

// Mock API
vi.mock('../api/runs', () => ({
  exportRun: vi.fn().mockResolvedValue({
    run_id: 'run-test-1',
    export_files: [
      { filename: 'Chandeliers_export.xlsx', template_id: 'tpl_abc', file_type: 'xlsx', product_count: 2 },
      { filename: 'Chandeliers_export.csv', template_id: 'tpl_abc', file_type: 'csv', product_count: 2 },
    ],
  }),
  listDownloads: vi.fn().mockResolvedValue([
    { filename: 'Chandeliers_export.xlsx', size_bytes: 12345, template_id: 'tpl_abc', file_type: 'xlsx' },
    { filename: 'Chandeliers_export.csv', size_bytes: 5678, template_id: 'tpl_abc', file_type: 'csv' },
  ]),
  createRun: vi.fn(),
  resolveRun: vi.fn(),
  previewRun: vi.fn(),
  patchValues: vi.fn(),
  validateRun: vi.fn(),
  getFindings: vi.fn(),
}))

const baseTemplate = {
  template_id: 'tpl_abc',
  filename: 'Chandeliers.xlsx',
  category: 'Chandeliers',
  fill_status: 'fillable',
  is_active: true,
  warnings: [],
  blocking_reasons: [],
  analysis_timestamp: '',
  registration_timestamp: '',
  category_status: 'resolved',
  template_purpose: 'listing_template',
  listing_sheet: 'Sheet1',
  header_row: 4,
  safe_write_start_row: 6,
}

const blockingFinding = {
  asin: 'B01TEST001A',
  sku: 'SKU1',
  column: 'Brand',
  value: '',
  severity: 'blocking',
  error_type: 'missing_required',
  recommended_action: 'Fix it',
}

// Mock store — use module-level variable that tests can swap
let mockFindings: unknown[] = []
let mockExportFiles: unknown[] = []

vi.mock('../store/runStore', () => ({
  useRunStore: () => ({
    runId: 'run-test-1',
    uploadedTemplates: [baseTemplate],
    findings: mockFindings,
    exportFiles: mockExportFiles,
    setExports: vi.fn(),
  }),
}))

import { ExportPage } from '../pages/ExportPage'

describe('ExportPage — no blocking findings', () => {
  beforeEach(() => {
    mockFindings = []
    mockExportFiles = []
  })

  it('Export button is enabled when no blocking findings', () => {
    render(
      <MemoryRouter>
        <ExportPage />
      </MemoryRouter>
    )
    const btn = screen.getByTestId('export-btn')
    expect(btn).not.toBeDisabled()
  })

  it('shows original templates unchanged message', () => {
    render(
      <MemoryRouter>
        <ExportPage />
      </MemoryRouter>
    )
    expect(screen.getByText(/never modified/i)).toBeTruthy()
  })
})

describe('ExportPage — with blocking findings', () => {
  beforeEach(() => {
    mockFindings = [blockingFinding]
    mockExportFiles = []
  })

  it('Export button is disabled with blocking findings', () => {
    render(
      <MemoryRouter>
        <ExportPage />
      </MemoryRouter>
    )
    const btn = screen.getByTestId('export-btn')
    expect(btn).toBeDisabled()
  })

  it('shows blocking issues warning banner', () => {
    render(
      <MemoryRouter>
        <ExportPage />
      </MemoryRouter>
    )
    expect(screen.getByText('Export blocked')).toBeTruthy()
  })
})

describe('ExportPage — download buttons', () => {
  beforeEach(() => {
    mockFindings = []
    mockExportFiles = [
      { filename: 'Chandeliers_export.xlsx', template_id: 'tpl_abc', file_type: 'xlsx', product_count: 2 },
    ]
  })

  it('shows generate exports button', () => {
    render(
      <MemoryRouter>
        <ExportPage />
      </MemoryRouter>
    )
    expect(screen.getByText('Generate Exports')).toBeTruthy()
  })
})
