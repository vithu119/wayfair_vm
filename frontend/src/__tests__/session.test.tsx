import { describe, it, expect, beforeEach } from 'vitest'
import { useRunStore } from '../store/runStore'

// Reset store before each test
beforeEach(() => {
  useRunStore.getState().resetRun()
})

describe('RunStore', () => {
  it('initializes with null runId', () => {
    const state = useRunStore.getState()
    expect(state.runId).toBeNull()
  })

  it('setRunId updates runId', () => {
    useRunStore.getState().setRunId('run-abc-123')
    expect(useRunStore.getState().runId).toBe('run-abc-123')
  })

  it('setAsins updates asins', () => {
    useRunStore.getState().setAsins(['B01EXAMPLE1', 'B02EXAMPLE2'])
    expect(useRunStore.getState().asins).toEqual(['B01EXAMPLE1', 'B02EXAMPLE2'])
  })

  it('setManualEdit adds to manualEdits', () => {
    useRunStore.getState().setManualEdit('B01EXAMPLE1::Brand', 'TestBrand')
    expect(useRunStore.getState().manualEdits['B01EXAMPLE1::Brand']).toBe('TestBrand')
  })

  it('resetRun clears all state', () => {
    const store = useRunStore.getState()
    store.setRunId('run-123')
    store.setAsins(['B01EXAMPLE1'])
    store.setManualEdit('B01EXAMPLE1::Brand', 'TestBrand')
    store.resetRun()

    const s = useRunStore.getState()
    expect(s.runId).toBeNull()
    expect(s.asins).toHaveLength(0)
    expect(s.manualEdits).toEqual({})
    expect(s.uploadedTemplates).toHaveLength(0)
  })

  it('addTemplate deduplicates by template_id', () => {
    const template = {
      template_id: 'tpl_abc',
      filename: 'test.xlsx',
      category: 'Test',
      category_status: 'resolved',
      template_purpose: 'listing_template',
      fill_status: 'fillable',
      listing_sheet: null,
      header_row: null,
      safe_write_start_row: null,
      is_active: true,
      warnings: [],
      blocking_reasons: [],
      analysis_timestamp: '',
      registration_timestamp: '',
    }
    const store = useRunStore.getState()
    store.addTemplate(template)
    store.addTemplate({ ...template, filename: 'test_updated.xlsx' })
    expect(useRunStore.getState().uploadedTemplates).toHaveLength(1)
    expect(useRunStore.getState().uploadedTemplates[0].filename).toBe('test_updated.xlsx')
  })

  it('approveTemplate adds to sessionApprovedTemplates', () => {
    useRunStore.getState().approveTemplate('tpl_abc')
    expect(useRunStore.getState().sessionApprovedTemplates.has('tpl_abc')).toBe(true)
  })

  it('revokeApproval removes from sessionApprovedTemplates', () => {
    const store = useRunStore.getState()
    store.approveTemplate('tpl_abc')
    store.revokeApproval('tpl_abc')
    expect(store.sessionApprovedTemplates.has('tpl_abc')).toBe(false)
  })
})
