import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../api/runs', () => ({
  createRun: vi.fn().mockResolvedValue({ run_id: 'run-test-1' }),
  resolveRun: vi.fn().mockResolvedValue({ run_id: 'run-test-1', products: [] }),
  previewRun: vi.fn().mockResolvedValue({
    run_id: 'run-test-1',
    rows: [
      {
        asin: 'B001234567',
        sku: 'SKU001',
        template_id: 'tpl_abc',
        cells: {
          'Product Name': { value: 'Test Lamp', status: 'source_value' },
          'Brand': { value: '', status: 'missing' },
          'Base Cost': { value: '29.99', status: 'source_value' },
          'Description': { value: '', status: 'unmapped' },
        },
      },
      {
        asin: 'B002345678',
        sku: 'SKU002',
        template_id: 'tpl_abc',
        cells: {
          'Product Name': { value: 'Floor Lamp', status: 'manual' },
          'Brand': { value: 'LampCo', status: 'source_value' },
          'Base Cost': { value: '49.99', status: 'source_value' },
          'Description': { value: '', status: 'unmapped' },
        },
      },
    ],
  }),
  patchValues: vi.fn().mockResolvedValue({}),
  getRun: vi.fn().mockResolvedValue({}),
  validateRun: vi.fn().mockResolvedValue({}),
  getFindings: vi.fn().mockResolvedValue({}),
  exportRun: vi.fn().mockResolvedValue({}),
  listDownloads: vi.fn().mockResolvedValue([]),
}))

vi.mock('../store/runStore', () => ({
  useRunStore: () => ({
    runId: 'run-test-1',
    setRunId: vi.fn(),
    uploadedTemplates: [{ template_id: 'tpl_abc', filename: 'Chandeliers.xlsx' }],
    sourceFiles: [{ source_id: 'src-1', filename: 'products.csv' }],
    asins: ['B001234567', 'B002345678'],
    manualEdits: {},
    setManualEdit: vi.fn(),
    setProducts: vi.fn(),
  }),
}))

import { PreviewPage } from '../pages/PreviewPage'

describe('PreviewPage', () => {
  it('renders Process button', () => {
    render(
      <MemoryRouter>
        <PreviewPage />
      </MemoryRouter>
    )
    expect(screen.getByText('Process')).toBeTruthy()
  })

  it('shows preview grid after processing', async () => {
    render(
      <MemoryRouter>
        <PreviewPage />
      </MemoryRouter>
    )
    fireEvent.click(screen.getByText('Process'))
    await waitFor(() => {
      expect(screen.getByText('B001234567')).toBeTruthy()
    }, { timeout: 3000 })
  })

  it('shows exact headers from template', async () => {
    render(
      <MemoryRouter>
        <PreviewPage />
      </MemoryRouter>
    )
    fireEvent.click(screen.getByText('Process'))
    await waitFor(() => {
      expect(screen.getByText('Product Name')).toBeTruthy()
      expect(screen.getByText('Brand')).toBeTruthy()
      expect(screen.getByText('Base Cost')).toBeTruthy()
    }, { timeout: 3000 })
  })

  it('shows filter buttons after processing', async () => {
    render(
      <MemoryRouter>
        <PreviewPage />
      </MemoryRouter>
    )
    fireEvent.click(screen.getByText('Process'))
    await waitFor(() => {
      expect(screen.getByText(/Missing required/)).toBeTruthy()
    }, { timeout: 3000 })
  })

  it('header order matches template column order', async () => {
    render(
      <MemoryRouter>
        <PreviewPage />
      </MemoryRouter>
    )
    fireEvent.click(screen.getByText('Process'))
    await waitFor(() => {
      const headers = screen.getAllByRole('columnheader')
      const headerTexts = headers.map((h) => h.textContent ?? '')
      // Product Name should come before Brand in the order
      const pnIdx = headerTexts.indexOf('Product Name')
      const brandIdx = headerTexts.indexOf('Brand')
      expect(pnIdx).toBeLessThan(brandIdx)
    }, { timeout: 3000 })
  })
})
