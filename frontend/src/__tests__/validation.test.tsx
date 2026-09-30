import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../api/runs', () => ({
  validateRun: vi.fn().mockResolvedValue({
    findings: [
      { asin: 'B001234567', sku: 'SKU001', column: 'Brand', value: '', severity: 'blocking', error_type: 'missing_required', recommended_action: 'Provide a value for Brand' },
    ],
  }),
  getFindings: vi.fn().mockResolvedValue({
    blocking: [{ asin: 'B001234567', sku: 'SKU001', column: 'Brand', value: '', severity: 'blocking', error_type: 'missing_required', recommended_action: 'Provide a value for Brand' }],
    error: [{ asin: 'B002345678', sku: 'SKU002', column: 'source_data', value: '', severity: 'error', error_type: 'unmatched_asin', recommended_action: 'Provide source data' }],
    warning: [{ asin: 'B001234567', sku: 'SKU001', column: 'Product Name', value: 'ok', severity: 'warning', error_type: 'truncation_risk', recommended_action: 'Check length' }],
    review: [],
    info: [],
  }),
  createRun: vi.fn(),
  resolveRun: vi.fn(),
  previewRun: vi.fn(),
  patchValues: vi.fn(),
  exportRun: vi.fn(),
  listDownloads: vi.fn(),
}))

vi.mock('../store/runStore', () => ({
  useRunStore: () => ({
    runId: 'run-test-1',
    findings: [
      { asin: 'B001234567', sku: 'SKU001', column: 'Brand', value: '', severity: 'blocking', error_type: 'missing_required', recommended_action: 'Provide a value for Brand' },
      { asin: 'B001234567', sku: 'SKU001', column: 'Product Name', value: 'ok', severity: 'warning', error_type: 'truncation_risk', recommended_action: 'Check length' },
      { asin: 'B002345678', sku: 'SKU002', column: 'source_data', value: '', severity: 'error', error_type: 'unmatched_asin', recommended_action: 'Provide source data' },
    ],
    setFindings: vi.fn(),
  }),
}))

import { ValidationPage } from '../pages/ValidationPage'

describe('ValidationPage', () => {
  it('renders severity summary', () => {
    render(
      <MemoryRouter>
        <ValidationPage />
      </MemoryRouter>
    )
    expect(screen.getByTestId('severity-summary')).toBeTruthy()
  })

  it('shows blocking count as 1', () => {
    render(
      <MemoryRouter>
        <ValidationPage />
      </MemoryRouter>
    )
    // blocking=1 in the summary
    const summary = screen.getByTestId('severity-summary')
    expect(summary.textContent).toContain('1')
  })

  it('renders findings table with data', () => {
    render(
      <MemoryRouter>
        <ValidationPage />
      </MemoryRouter>
    )
    expect(screen.getByTestId('findings-table')).toBeTruthy()
    expect(screen.getAllByText('B001234567').length).toBeGreaterThan(0)
  })

  it('Revalidate button is present and clickable', () => {
    render(
      <MemoryRouter>
        <ValidationPage />
      </MemoryRouter>
    )
    const btn = screen.getByTestId('revalidate-btn')
    expect(btn).toBeTruthy()
    expect(btn).not.toBeDisabled()
  })

  it('Revalidate button calls validateRun API', async () => {
    const { validateRun } = await import('../api/runs')
    render(
      <MemoryRouter>
        <ValidationPage />
      </MemoryRouter>
    )
    fireEvent.click(screen.getByTestId('revalidate-btn'))
    await waitFor(() => {
      expect(validateRun).toHaveBeenCalledWith('run-test-1')
    })
  })

  it('severity filters are available', () => {
    render(
      <MemoryRouter>
        <ValidationPage />
      </MemoryRouter>
    )
    // Filter bar renders All + severity buttons
    expect(screen.getByText(/^All/)).toBeTruthy()
  })
})
