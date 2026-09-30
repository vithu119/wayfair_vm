import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useRunStore } from '../store/runStore'
import { validateAsins } from '../api/asins'
import { FilterBar } from '../components/FilterBar'
import { EmptyState } from '../components/EmptyState'
import type { AsinValidationItem } from '../types'

type InputTab = 'paste' | 'file' | 'source'

function parseAsinInput(text: string): string[] {
  return text
    .split(/[\n,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

export function AsinsPage() {
  const { asins, setAsins, asinItems, setAsinItems, sourceFiles, setBatchAsinText, setAutoRunBatch, setBatchResponse, resetDownstream } = useRunStore()
  const navigate = useNavigate()
  const [tab, setTab] = useState<InputTab>('paste')
  const [pasteText, setPasteText] = useState(() => asins.join('\n'))
  const [items, setItems] = useState<AsinValidationItem[]>(() => asinItems)
  const [validating, setValidating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('all')

  const runValidation = async (rawList: string[]) => {
    if (!rawList.length) return
    setValidating(true)
    setError(null)
    try {
      const result = await validateAsins(rawList)
      // Sort by parent_sku (nulls last), then by normalized ASIN — groups families together
      const sorted = [...result.items].sort((a, b) => {
        const pa = a.parent_sku ?? '￿'
        const pb = b.parent_sku ?? '￿'
        if (pa !== pb) return pa.localeCompare(pb)
        return a.normalized.localeCompare(b.normalized)
      })
      setItems(sorted)
      setAsinItems(sorted)
      const validNorm = sorted
        .filter((i) => i.valid && !i.duplicate)
        .map((i) => i.normalized)
      setAsins(validNorm)
      resetDownstream()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setValidating(false)
    }
  }

  const handlePasteValidate = () => {
    const parsed = parseAsinInput(pasteText)
    runValidation(parsed)
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const text = await file.text()
    const parsed = parseAsinInput(text)
    runValidation(parsed)
    e.target.value = ''
  }

  const handleFromSource = () => {
    const extracted: string[] = []
    for (const src of sourceFiles) {
      for (const row of src.preview) {
        const asinCol = src.asin_column
        if (asinCol && row[asinCol]) extracted.push(row[asinCol])
      }
    }
    if (!extracted.length) {
      setError('No ASINs found in uploaded sources. Check your source ASIN column detection.')
      return
    }
    runValidation(extracted)
  }

  const handleRemove = (normalized: string) => {
    const next = items.filter((i) => i.normalized !== normalized)
    setItems(next)
    setAsinItems(next)
    setAsins(next.filter((i) => i.valid && !i.duplicate).map((i) => i.normalized))
  }

  const validCount = items.filter((i) => i.valid && !i.duplicate).length
  const filtered = items.filter((item) => {
    if (filter === 'all') return true
    if (filter === 'valid') return item.valid && !item.duplicate
    if (filter === 'invalid') return !item.valid
    if (filter === 'duplicate') return item.duplicate
    return true
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">ASINs</h1>
        <p className="text-sm text-gray-500 mt-1">Enter or upload the ASINs to process</p>
      </div>

      <div className="flex gap-2">
        {(['paste', 'file', 'source'] as InputTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium capitalize ${
              tab === t ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            {t === 'paste' ? 'Paste' : t === 'file' ? 'File Upload' : 'From Source'}
          </button>
        ))}
      </div>

      {tab === 'paste' && (
        <div className="space-y-3">
          <textarea
            className="w-full h-32 border rounded-lg p-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="B01EXAMPLE1&#10;B02EXAMPLE2&#10;(one per line, or comma/space separated)"
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
          />
          <button
            onClick={handlePasteValidate}
            disabled={!pasteText.trim() || validating}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm disabled:opacity-50"
          >
            {validating ? 'Validating...' : 'Validate ASINs'}
          </button>
        </div>
      )}

      {tab === 'file' && (
        <div className="space-y-3">
          <p className="text-sm text-gray-600">Upload a CSV or TXT file with one ASIN per line</p>
          <label className="inline-block">
            <span className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm cursor-pointer hover:bg-blue-700">
              Choose File
            </span>
            <input type="file" accept=".csv,.txt" className="hidden" onChange={handleFileUpload} />
          </label>
        </div>
      )}

      {tab === 'source' && (
        <div className="space-y-3">
          <p className="text-sm text-gray-600">
            Extract ASINs from your uploaded data sources ({sourceFiles.length} source(s) loaded)
          </p>
          <button
            onClick={handleFromSource}
            disabled={!sourceFiles.length || validating}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm disabled:opacity-50"
          >
            Extract ASINs from Sources
          </button>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>
      )}

      {items.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <FilterBar
              options={[
                { key: 'all', label: 'All', count: items.length },
                { key: 'valid', label: 'Valid', count: items.filter(i => i.valid && !i.duplicate).length },
                { key: 'invalid', label: 'Invalid', count: items.filter(i => !i.valid).length },
                { key: 'duplicate', label: 'Duplicate', count: items.filter(i => i.duplicate).length },
              ]}
              active={filter}
              onChange={setFilter}
            />
            <button
              disabled={validCount === 0}
              onClick={() => {
                const validAsins = items.filter(i => i.valid && !i.duplicate).map(i => i.normalized)
                setBatchAsinText(validAsins.join('\n'))
                setBatchResponse(null)
                setAutoRunBatch(true)
                navigate('/content')
              }}
              className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm disabled:opacity-50 hover:bg-green-700 transition-colors"
            >
              Continue with {validCount} valid ASIN{validCount !== 1 ? 's' : ''} →
            </button>
          </div>

          <div className="overflow-x-auto rounded-lg border border-gray-200">
            {(() => {
              // Build set of SKUs that appear more than once across all items
              const skuCounts: Record<string, number> = {}
              for (const it of items) {
                if (it.sku) skuCounts[it.sku] = (skuCounts[it.sku] ?? 0) + 1
              }
              const dupSkus = new Set(Object.keys(skuCounts).filter(s => skuCounts[s] > 1))
              return (
                <table className="w-full text-sm" data-testid="asin-table">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Family (Parent SKU)</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">ASIN</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">SKU</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Status</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {filtered.map((item, i) => {
                      const prevFamily = i > 0 ? (filtered[i - 1].parent_sku ?? null) : null
                      const thisFamily = item.parent_sku ?? null
                      const newFamily = thisFamily !== prevFamily
                      const skuIsDup = item.sku ? dupSkus.has(item.sku) : false
                      const rowBg = !item.valid ? 'bg-red-50' : item.duplicate ? 'bg-yellow-50' : ''
                      return (
                        <tr key={i} className={`${rowBg} ${newFamily && i > 0 ? 'border-t-2 border-blue-200' : ''}`}>
                          <td className="px-3 py-2 font-mono text-xs text-blue-700 font-medium">
                            {thisFamily ?? <span className="text-gray-400 font-normal">—</span>}
                          </td>
                          <td className="px-3 py-2 font-mono text-xs">{item.normalized}</td>
                          <td className={`px-3 py-2 font-mono text-xs ${skuIsDup ? 'bg-orange-100 text-orange-700 font-semibold' : 'text-gray-700'}`}>
                            {item.sku
                              ? <>{item.sku}{skuIsDup && <span className="ml-1 text-orange-500 text-xs">⚠ dup SKU</span>}</>
                              : <span className="text-gray-400">—</span>}
                          </td>
                          <td className="px-3 py-2">
                            {item.valid && !item.duplicate ? (
                              <span className="text-green-600 text-xs">Valid</span>
                            ) : item.duplicate ? (
                              <span className="text-yellow-600 text-xs">Duplicate</span>
                            ) : (
                              <span className="text-red-600 text-xs" title={item.reason ?? ''}>Invalid</span>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <button
                              onClick={() => handleRemove(item.normalized)}
                              className="text-xs text-red-500 hover:underline"
                            >
                              Remove
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )
            })()}
          </div>
        </div>
      )}

      {items.length === 0 && !validating && (
        <EmptyState icon="🔎" title="No ASINs yet" message="Enter ASINs to validate them" />
      )}
    </div>
  )
}
