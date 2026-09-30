import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../api/sources', () => ({
  uploadCsv: vi.fn().mockResolvedValue({
    source_id: 'src-1',
    filename: 'products.csv',
    row_count: 10,
    columns: ['asin', 'sku', 'product_name'],
    asin_column: 'asin',
    sku_column: 'sku',
    category_column: null,
    preview: [],
  }),
  uploadExcel: vi.fn().mockResolvedValue({
    source_id: 'src-2',
    filename: 'products.xlsx',
    row_count: 5,
    columns: ['asin', 'brand'],
    asin_column: 'asin',
    sku_column: null,
    category_column: null,
    preview: [],
    sheet_names: ['Sheet1', 'Sheet2'],
    chosen_sheet: 'Sheet1',
  }),
  previewSource: vi.fn().mockResolvedValue({ source_id: 'src-1', filename: 'products.csv', row_count: 10, columns: [], asin_column: null, preview: [] }),
}))

vi.mock('../store/runStore', () => ({
  useRunStore: () => ({
    sourceFiles: [
      {
        source_id: 'src-1',
        filename: 'products.csv',
        row_count: 10,
        columns: ['asin', 'sku'],
        asin_column: 'asin',
        sku_column: 'sku',
        category_column: null,
        preview: [],
      },
      {
        source_id: 'src-2',
        filename: 'products.xlsx',
        row_count: 5,
        columns: ['asin', 'brand'],
        asin_column: 'asin',
        sku_column: null,
        category_column: null,
        preview: [],
        sheet_names: ['Sheet1', 'Sheet2'],
        chosen_sheet: 'Sheet1',
      },
    ],
    addSource: vi.fn(),
  }),
}))

import { DataSourcesPage } from '../pages/DataSourcesPage'

describe('DataSourcesPage', () => {
  it('renders CSV upload table with source data', () => {
    render(
      <MemoryRouter>
        <DataSourcesPage />
      </MemoryRouter>
    )
    expect(screen.getByTestId('csv-table')).toBeTruthy()
    expect(screen.getByText('products.csv')).toBeTruthy()
  })

  it('shows ASIN column detection', () => {
    render(
      <MemoryRouter>
        <DataSourcesPage />
      </MemoryRouter>
    )
    // 'asin' appears in the table cell for ASIN column
    const cells = screen.getAllByText('asin')
    expect(cells.length).toBeGreaterThan(0)
  })

  it('renders Excel sheet selector when excel sources present', async () => {
    const { getByText, container } = render(
      <MemoryRouter>
        <DataSourcesPage />
      </MemoryRouter>
    )
    // Switch to excel tab
    const excelBtn = getByText('Excel Upload')
    excelBtn.click()
    // Sheet selector should be present for excel sources
    await new Promise((r) => setTimeout(r, 0))
    const selectors = container.querySelectorAll('[data-testid="sheet-selector"]')
    expect(selectors.length).toBeGreaterThan(0)
  })
})
