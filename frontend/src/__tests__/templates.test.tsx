import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { StatusBadge } from '../components/StatusBadge'
import { FileDropzone } from '../components/FileDropzone'
import { TemplateDetails } from '../components/TemplateDetails'
import type { TemplateEntry } from '../types'

vi.mock('../api/templates', () => ({
  uploadTemplates: vi.fn().mockResolvedValue([]),
  listTemplates: vi.fn().mockResolvedValue([]),
  getTemplate: vi.fn().mockResolvedValue({}),
  activateTemplate: vi.fn().mockResolvedValue({}),
}))

const mockTemplate: TemplateEntry = {
  template_id: 'tpl_abc123',
  filename: 'Chandeliers.xlsx',
  category: 'Chandeliers',
  category_status: 'resolved',
  template_purpose: 'listing_template',
  fill_status: 'fillable',
  listing_sheet: 'Item & Listing Data',
  header_row: 4,
  safe_write_start_row: 6,
  is_active: true,
  warnings: ['Test warning'],
  blocking_reasons: [],
  analysis_timestamp: '2026-01-01T00:00:00Z',
  registration_timestamp: '2026-01-01T00:00:00Z',
}

describe('StatusBadge', () => {
  it('renders fillable with green styling', () => {
    const { container } = render(<StatusBadge status="fillable" />)
    const badge = container.querySelector('span')
    expect(badge).toBeTruthy()
    expect(badge?.className).toContain('green')
  })

  it('renders fillable_with_warnings with yellow styling', () => {
    const { container } = render(<StatusBadge status="fillable_with_warnings" />)
    const badge = container.querySelector('span')
    expect(badge?.className).toContain('yellow')
  })

  it('renders requires_review with amber styling', () => {
    const { container } = render(<StatusBadge status="requires_review" />)
    const badge = container.querySelector('span')
    expect(badge?.className).toContain('amber')
  })

  it('renders not_fillable with red styling', () => {
    const { container } = render(<StatusBadge status="not_fillable" />)
    const badge = container.querySelector('span')
    expect(badge?.className).toContain('red')
  })

  it('uses custom label when provided', () => {
    render(<StatusBadge status="fillable" label="Ready" />)
    expect(screen.getByText('Ready')).toBeTruthy()
  })
})

describe('TemplateDetails modal', () => {
  it('renders template information', () => {
    render(
      <MemoryRouter>
        <TemplateDetails template={mockTemplate} onClose={() => {}} />
      </MemoryRouter>
    )
    expect(screen.getByText('Chandeliers.xlsx')).toBeTruthy()
    expect(screen.getByText('Chandeliers')).toBeTruthy()
  })

  it('shows warnings', () => {
    render(
      <MemoryRouter>
        <TemplateDetails template={mockTemplate} onClose={() => {}} />
      </MemoryRouter>
    )
    expect(screen.getByText('Test warning')).toBeTruthy()
  })

  it('calls onClose when Close button is clicked', () => {
    const onClose = vi.fn()
    render(
      <MemoryRouter>
        <TemplateDetails template={mockTemplate} onClose={onClose} />
      </MemoryRouter>
    )
    fireEvent.click(screen.getByText('Close'))
    expect(onClose).toHaveBeenCalled()
  })

  it('returns null when template is null', () => {
    const { container } = render(
      <MemoryRouter>
        <TemplateDetails template={null} onClose={() => {}} />
      </MemoryRouter>
    )
    expect(container.firstChild).toBeNull()
  })
})

describe('FileDropzone', () => {
  it('renders with label', () => {
    render(<FileDropzone onFiles={() => {}} label="Drop files here" />)
    expect(screen.getByText('Drop files here')).toBeTruthy()
  })

  it('shows accepted file types', () => {
    render(<FileDropzone onFiles={() => {}} accept={['xlsx', 'csv']} />)
    expect(screen.getByText(/xlsx.*csv|csv.*xlsx/)).toBeTruthy()
  })

  it('calls onFiles with accepted files on drop', () => {
    const onFiles = vi.fn()
    const { container } = render(
      <FileDropzone onFiles={onFiles} accept={['xlsx']} />
    )
    const zone = container.firstChild as HTMLElement
    const file = new File(['test'], 'test.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    fireEvent.drop(zone, { dataTransfer: { files: [file] } })
    expect(onFiles).toHaveBeenCalledWith([file])
  })

  it('filters out rejected file types on drop', () => {
    const onFiles = vi.fn()
    const { container } = render(
      <FileDropzone onFiles={onFiles} accept={['xlsx']} />
    )
    const zone = container.firstChild as HTMLElement
    const file = new File(['test'], 'test.txt', { type: 'text/plain' })
    fireEvent.drop(zone, { dataTransfer: { files: [file] } })
    expect(onFiles).not.toHaveBeenCalled()
  })
})
