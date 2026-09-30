import React, { useState, useCallback, useEffect, useRef } from 'react'
import { useRunStore } from '../store/runStore'
import { createRun, resolveRun, previewRun, patchValues } from '../api/runs'
import { FilterBar } from '../components/FilterBar'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import { CellEditor } from '../components/CellEditor'

const CELL_STATUS_STYLES: Record<string, string> = {
  source_value: 'bg-white',
  missing: 'bg-yellow-50 border border-yellow-200',
  invalid: 'bg-red-50 border border-red-200',
  manual: 'bg-blue-50 border border-blue-200',
  unmapped: 'bg-gray-50',
  fixed_value: 'bg-green-50',
}

const CELL_DOT_COLORS: Record<string, string> = {
  source_value: 'bg-green-500',
  missing: 'bg-yellow-400',
  invalid: 'bg-red-500',
  manual: 'bg-blue-500',
  unmapped: 'bg-gray-300',
  fixed_value: 'bg-green-300',
}

const PROCESSING_STAGES = [
  'Creating run session',
  'Loading templates',
  'Loading source data',
  'Matching ASINs to products',
  'Routing to templates',
  'Applying field mappings',
  'Checking fixed values',
  'Building preview grid',
]

export function PreviewPage() {
  const { runId, setRunId, uploadedTemplates, sourceFiles, asins, manualEdits, setManualEdit, setProducts, previewRows: rows, previewHeaders: headers, setPreviewRows } = useRunStore()
  const [loading, setLoading] = useState(false)
  const [stage, setStage] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('all')
  const [colFilter, setColFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [selectedAsin, setSelectedAsin] = useState<string | null>(null)
  const autoProcessed = useRef(false)

  // Auto-process when the user arrives with templates+ASINs set up but no preview rows yet
  useEffect(() => {
    if (autoProcessed.current) return
    if (rows.length > 0) return
    if (!asins.length || !uploadedTemplates.length) return
    autoProcessed.current = true
    handleProcess()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleProcess = async () => {
    setLoading(true)
    setError(null)
    setStage(0)

    try {
      setStage(1)
      // Re-use existing run if present (preserves manual edits from Content page).
      // Create a fresh run only when there is none, or verify the existing one is still alive.
      let rid = runId
      let needsEditRestore = false
      if (!rid) {
        const res = await createRun()
        rid = res.run_id
        setRunId(rid)
        needsEditRestore = true
      } else {
        // Ping the existing run — if it's gone (server restart) create a new one
        try {
          const check = await fetch(`/api/runs/${rid}`)
          if (!check.ok) {
            const res = await createRun()
            rid = res.run_id
            setRunId(rid)
            needsEditRestore = true
          }
        } catch {
          const res = await createRun()
          rid = res.run_id
          setRunId(rid)
          needsEditRestore = true
        }
      }
      // Re-upload manualEdits from localStorage to the new server-side run.
      // This recovers edits after a server restart that wiped in-memory state.
      if (needsEditRestore && Object.keys(manualEdits).length > 0) {
        await patchValues(rid, manualEdits)
      }

      setStage(2)
      const templateIds = uploadedTemplates.map((t) => t.template_id)
      const sourceIds = sourceFiles.map((s) => s.source_id)

      // Include cached profiles so backend can work even after ephemeral filesystem wipe
      const inlineProfiles: Record<string, unknown> = {}
      for (const t of uploadedTemplates) {
        if (t.profile) inlineProfiles[t.template_id] = t.profile
      }

      setStage(3)
      const resolveRes = await resolveRun(rid, {
        template_ids: templateIds,
        source_ids: sourceIds,
        asins,
        template_profiles: Object.keys(inlineProfiles).length ? inlineProfiles : undefined,
      })
      setProducts(resolveRes.products ?? [])
      setStage(5)

      setStage(7)
      const preview = await previewRun(rid)
      const allRows = preview.rows ?? []
      const allHeaders = allRows.length > 0 ? Object.keys(allRows[0].cells) : []
      setPreviewRows(allRows, allHeaders)
      setStage(8)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleCellSave = useCallback(
    async (asin: string, header: string, value: string) => {
      const key = `${asin}::${header}`
      setManualEdit(key, value)
      if (runId) {
        try {
          await patchValues(runId, { [key]: value })
          const updated = rows.map((r) =>
            r.asin === asin
              ? { ...r, cells: { ...r.cells, [header]: { value, status: 'manual' as const } } }
              : r
          )
          setPreviewRows(updated, headers)
        } catch (e) {
          // silently ignore
        }
      }
    },
    [runId, setManualEdit]
  )

  const filteredRows = rows.filter((row) => {
    if (search) {
      const q = search.toLowerCase()
      if (
        !row.asin.toLowerCase().includes(q) &&
        !(row.sku ?? '').toLowerCase().includes(q)
      ) return false
    }
    if (filter === 'ready') {
      return !Object.values(row.cells).some((c) => c.status === 'missing')
    }
    if (filter === 'missing') {
      return Object.values(row.cells).some((c) => c.status === 'missing')
    }
    if (filter === 'edited') {
      return Object.values(row.cells).some((c) => c.status === 'manual')
    }
    return true
  })

  const filteredHeaders = headers.filter((h) => {
    if (colFilter === 'all') return true
    if (colFilter === 'populated') return filteredRows.some((r) => r.cells[h]?.value)
    if (colFilter === 'empty') return filteredRows.every((r) => !r.cells[h]?.value)
    if (colFilter === 'edited') return filteredRows.some((r) => r.cells[h]?.status === 'manual')
    return true
  })

  const visibleHeaders = filteredHeaders.slice(0, 50) // cap for performance

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Preview</h1>
          <p className="text-sm text-gray-500 mt-1">Review and edit product data before export</p>
        </div>
        <button
          onClick={handleProcess}
          disabled={loading || !asins.length || !uploadedTemplates.length}
          className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50"
        >
          {loading ? 'Processing...' : 'Process'}
        </button>
      </div>

      {loading && (
        <div className="space-y-3">
          <LoadingSpinner message={PROCESSING_STAGES[Math.max(0, stage - 1)] ?? 'Processing...'} />
          <div className="space-y-1 max-w-sm">
            {PROCESSING_STAGES.map((s, i) => (
              <div key={i} className={`flex items-center gap-2 text-xs ${i < stage ? 'text-green-600' : i === stage ? 'text-blue-600' : 'text-gray-300'}`}>
                <span>{i < stage ? '✓' : i === stage ? '◉' : '○'}</span>
                <span>{s}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>
      )}

      {!loading && rows.length > 0 && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <input
              type="text"
              placeholder="Search by ASIN or SKU..."
              className="border rounded px-3 py-1.5 text-sm w-48"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <FilterBar
              options={[
                { key: 'all', label: 'All', count: rows.length },
                { key: 'ready', label: 'Ready' },
                { key: 'missing', label: 'Missing required' },
                { key: 'edited', label: 'Edited' },
              ]}
              active={filter}
              onChange={setFilter}
            />
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Columns:</span>
            <FilterBar
              options={[
                { key: 'all', label: 'All' },
                { key: 'populated', label: 'Populated' },
                { key: 'empty', label: 'Empty' },
                { key: 'edited', label: 'Edited' },
              ]}
              active={colFilter}
              onChange={setColFilter}
            />
          </div>

          <div className="text-xs text-gray-500 flex gap-4">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500 inline-block" /> Mapped from source</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-yellow-400 inline-block" /> Missing</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500 inline-block" /> Manual edit</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gray-300 inline-block" /> Unmapped</span>
          </div>

          <div className="overflow-x-auto rounded-lg border border-gray-200 max-h-[60vh]">
            <table className="text-xs border-collapse min-w-full">
              <thead className="bg-gray-50 sticky top-0 z-10">
                <tr>
                  <th className="sticky left-0 z-20 bg-gray-50 px-2 py-2 text-left font-medium text-gray-500 border-r border-b whitespace-nowrap">ASIN</th>
                  <th className="sticky left-20 z-20 bg-gray-50 px-2 py-2 text-left font-medium text-gray-500 border-r border-b whitespace-nowrap">SKU</th>
                  {visibleHeaders.map((h) => (
                    <th key={h} className="px-2 py-2 text-left font-medium text-gray-500 border-b whitespace-nowrap min-w-[120px]">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row) => (
                  <tr
                    key={row.asin}
                    className={`border-t hover:bg-gray-50/50 ${selectedAsin === row.asin ? 'bg-blue-50' : ''}`}
                    onClick={() => setSelectedAsin(row.asin === selectedAsin ? null : row.asin)}
                  >
                    <td className="sticky left-0 z-10 bg-white border-r px-2 py-1 font-mono">{row.asin}</td>
                    <td className="sticky left-20 z-10 bg-white border-r px-2 py-1 font-mono">{row.sku ?? '—'}</td>
                    {visibleHeaders.map((h) => {
                      const cell = row.cells[h] ?? { value: '', status: 'unmapped' }
                      const dotColor = CELL_DOT_COLORS[cell.status] ?? 'bg-gray-300'
                      const bgStyle = CELL_STATUS_STYLES[cell.status] ?? ''
                      return (
                        <td key={h} className={`px-1 py-1 min-w-[120px] max-w-[200px] ${bgStyle}`}>
                          <div className="flex items-center gap-1">
                            <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotColor}`} />
                            <CellEditor
                              value={cell.value}
                              onSave={(v) => handleCellSave(row.asin, h, v)}
                            />
                          </div>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {visibleHeaders.length < filteredHeaders.length && (
            <p className="text-xs text-gray-400">
              Showing {visibleHeaders.length} of {filteredHeaders.length} columns. Use column filter to narrow results.
            </p>
          )}
        </div>
      )}

      {!loading && rows.length === 0 && !error && (
        <EmptyState
          icon="👁"
          title="No preview yet"
          message="Click Process to resolve products and build the preview grid"
        />
      )}
    </div>
  )
}
