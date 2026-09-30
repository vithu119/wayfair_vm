import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

// Helper to simulate the ASIN parsing logic independent of component
function parseAsinInput(text: string): string[] {
  return text
    .split(/[\n,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

// Helper to simulate ASIN validation
function isValidAsin(raw: string): boolean {
  return /^[A-Z0-9]{10}$/.test(raw.trim().toUpperCase())
}

describe('ASIN parsing', () => {
  it('parses newline-separated ASINs', () => {
    const result = parseAsinInput('B01EXAMPLE1\nB02EXAMPLE2\nB03EXAMPLE3')
    expect(result).toEqual(['B01EXAMPLE1', 'B02EXAMPLE2', 'B03EXAMPLE3'])
  })

  it('parses comma-separated ASINs', () => {
    const result = parseAsinInput('B01EXAMPLE1,B02EXAMPLE2,B03EXAMPLE3')
    expect(result).toEqual(['B01EXAMPLE1', 'B02EXAMPLE2', 'B03EXAMPLE3'])
  })

  it('parses space-separated ASINs', () => {
    const result = parseAsinInput('B01EXAMPLE1 B02EXAMPLE2 B03EXAMPLE3')
    expect(result).toEqual(['B01EXAMPLE1', 'B02EXAMPLE2', 'B03EXAMPLE3'])
  })

  it('handles mixed separators', () => {
    const result = parseAsinInput('B01EXAMPLE1, B02EXAMPLE2\nB03EXAMPLE3')
    expect(result).toEqual(['B01EXAMPLE1', 'B02EXAMPLE2', 'B03EXAMPLE3'])
  })

  it('strips whitespace from each ASIN', () => {
    const result = parseAsinInput('  B01EXAMPLE1  ')
    expect(result).toEqual(['B01EXAMPLE1'])
  })

  it('filters empty strings', () => {
    const result = parseAsinInput('B01EXAMPLE1\n\n\nB02EXAMPLE2')
    expect(result).toEqual(['B01EXAMPLE1', 'B02EXAMPLE2'])
  })
})

describe('ASIN format validation', () => {
  it('accepts valid 10-char alphanumeric starting with B', () => {
    expect(isValidAsin('B001234567')).toBe(true)
  })

  it('accepts valid 10-char alphanumeric not starting with B', () => {
    expect(isValidAsin('A001234567')).toBe(true)
  })

  it('rejects too-short ASINs', () => {
    expect(isValidAsin('B01')).toBe(false)
  })

  it('rejects too-long ASINs', () => {
    expect(isValidAsin('B001234567890')).toBe(false)
  })

  it('rejects ASINs with special characters', () => {
    expect(isValidAsin('B001-23456')).toBe(false)
  })

  it('normalizes lowercase to uppercase', () => {
    expect(isValidAsin('b001234567')).toBe(true)
  })
})

describe('Duplicate detection', () => {
  it('detects duplicate ASINs', () => {
    const asins = ['B01EXAMPLE1', 'B02EXAMPLE2', 'B01EXAMPLE1']
    const seen = new Set<string>()
    const duplicates = asins.filter((a) => {
      const norm = a.toUpperCase()
      if (seen.has(norm)) return true
      seen.add(norm)
      return false
    })
    expect(duplicates).toEqual(['B01EXAMPLE1'])
  })

  it('does not flag unique ASINs as duplicates', () => {
    const asins = ['B01EXAMPLE1', 'B02EXAMPLE2', 'B03EXAMPLE3']
    const seen = new Set<string>()
    const duplicates = asins.filter((a) => {
      const norm = a.toUpperCase()
      if (seen.has(norm)) return true
      seen.add(norm)
      return false
    })
    expect(duplicates).toHaveLength(0)
  })
})

vi.mock('../api/asins', () => ({
  validateAsins: vi.fn().mockResolvedValue({
    items: [
      { input: 'B01EXAMPLE1', normalized: 'B01EXAMPLE1', valid: true, duplicate: false },
      { input: 'bad', normalized: 'BAD', valid: false, reason: 'Too short', duplicate: false },
    ],
    valid_count: 1,
    invalid_count: 1,
    duplicate_count: 0,
  }),
}))

vi.mock('../store/runStore', () => ({
  useRunStore: () => ({
    asins: [],
    setAsins: vi.fn(),
    sourceFiles: [],
  }),
}))

import { AsinsPage } from '../pages/AsinsPage'

describe('AsinsPage component', () => {
  it('renders paste tab by default', () => {
    render(
      <MemoryRouter>
        <AsinsPage />
      </MemoryRouter>
    )
    // The textarea placeholder contains "B01EXAMPLE1" — check for the textarea itself
    const textarea = document.querySelector('textarea')
    expect(textarea).toBeTruthy()
  })

  it('validates ASINs and shows results table', async () => {
    render(
      <MemoryRouter>
        <AsinsPage />
      </MemoryRouter>
    )
    const textarea = document.querySelector('textarea') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: 'B01EXAMPLE1\nbad' } })
    fireEvent.click(screen.getByText('Validate ASINs'))
    await waitFor(() => {
      expect(screen.getByTestId('asin-table')).toBeTruthy()
    })
  })
})
