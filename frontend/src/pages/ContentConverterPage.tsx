import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { convertContent, batchConvert } from '../api/content'
import type { ConvertResponse, BatchItemResult, BatchResponse } from '../api/content'
import { patchValues, createRun, sotFill } from '../api/runs'
import { useRunStore } from '../store/runStore'

// ── Shared micro-components ───────────────────────────────────────────────────

function QcBadge({ pass, status }: { pass: boolean; status: string }) {
  if (status === 'no_sot_data')
    return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-600">No SOT data</span>
  if (status === 'error')
    return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-700">Error</span>
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${pass ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'}`}>
      {pass ? '✓ PASS' : '⚠ REVIEW'}
    </span>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) }) }}
      className="text-xs text-blue-600 hover:underline ml-2 shrink-0"
    >
      {copied ? 'Copied!' : 'Copy'}
    </button>
  )
}

// ── Single converter ──────────────────────────────────────────────────────────

function SingleResultPanel({ result }: { result: ConvertResponse }) {
  const bulletsText = result.feature_bullets.map((b) => `• ${b}`).join('\n')
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-gray-800">Converted Output</h2>
        <QcBadge pass={result.qc_pass} status={result.status} />
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Product Name</span>
          <CopyButton text={result.product_name} />
        </div>
        <p className="text-sm text-gray-900">{result.product_name}</p>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Marketing Copy
            <span className="ml-2 text-gray-400 font-normal normal-case">{result.marketing_copy_word_count} words</span>
          </span>
          <CopyButton text={result.marketing_copy} />
        </div>
        <p className="text-sm text-gray-900 leading-relaxed">{result.marketing_copy}</p>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Feature Bullets
            <span className="ml-2 text-gray-400 font-normal normal-case">{result.feature_bullets.length} bullets</span>
          </span>
          <CopyButton text={bulletsText} />
        </div>
        <ul className="space-y-1">
          {result.feature_bullets.map((b, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-gray-900">
              <span className="text-gray-400 mt-0.5 select-none">•</span>
              <span>{b}</span>
              <span className="ml-auto text-xs text-gray-400 whitespace-nowrap">{b.split(' ').length}w</span>
            </li>
          ))}
        </ul>
      </div>

      {result.validation_errors.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <p className="text-xs font-semibold text-yellow-700 mb-2">QC Issues</p>
          <ul className="space-y-1">
            {result.validation_errors.map((e, i) => <li key={i} className="text-xs text-yellow-800">• {e}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

function SingleTab() {
  const { singleResult: result, setSingleResult: setResult, singleInputs, setSingleInputs, runId, setManualEdit, previewRows, previewHeaders, setPreviewRows } = useRunStore()
  const { title, bulletsText, description, variantsText, groupRefId } = singleInputs
  const setTitle = (v: string) => setSingleInputs({ title: v })
  const setBulletsText = (v: string) => setSingleInputs({ bulletsText: v })
  const setDescription = (v: string) => setSingleInputs({ description: v })
  const setVariantsText = (v: string) => setSingleInputs({ variantsText: v })
  const setGroupRefId = (v: string) => setSingleInputs({ groupRefId: v })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const parseBullets = (t: string) => t.split('\n').map((l) => l.replace(/^[\s•\-*]+/, '').trim()).filter(Boolean)
  const parseVariants = (t: string) => t.split(/[,\n]+/).map((v) => v.trim()).filter(Boolean)

  const handleConvert = async () => {
    setLoading(true); setError(null)
    try {
      const res = await convertContent({
        group_ref_id: groupRefId.trim(),
        amazon_title: title.trim(),
        amazon_bullets: parseBullets(bulletsText),
        amazon_description: description.trim(),
        variant_terms: parseVariants(variantsText),
      })
      setResult(res)
      // Auto-apply to active run so Preview reflects it immediately
      if (runId && res.product_name) {
        const ref = res.group_ref_id || groupRefId.trim() || 'single'
        const edits: Record<string, string> = {
          [`${ref}::Product Name`]: res.product_name,
          [`${ref}::Marketing Copy`]: res.marketing_copy,
        }
        res.feature_bullets.forEach((b, i) => { edits[`${ref}::Feature Bullet ${i + 1}`] = b })
        try {
          await patchValues(runId, edits)
          Object.entries(edits).forEach(([k, v]) => setManualEdit(k, v))
          if (previewRows.length > 0) {
            const updatedRows = previewRows.map((row) => {
              if (row.asin !== ref) return row
              const updatedCells = { ...row.cells }
              Object.entries(edits).forEach(([key, val]) => {
                const header = key.split('::').slice(1).join('::')
                updatedCells[header] = { value: val, status: 'manual' }
              })
              return { ...row, cells: updatedCells }
            })
            setPreviewRows(updatedRows, previewHeaders)
          }
        } catch { /* silent — conversion result is still shown */ }
      }
    } catch (e) { setError((e as Error).message) }
    finally { setLoading(false) }
  }

  const handleClear = () => { setSingleInputs({ title: '', bulletsText: '', description: '', variantsText: '', groupRefId: '' }); setResult(null); setError(null) }


  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Group / Product Reference ID <span className="text-gray-400">(optional)</span></label>
          <input type="text" className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="e.g. GRP-001" value={groupRefId} onChange={(e) => setGroupRefId(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Amazon Title <span className="text-red-500">*</span></label>
          <input type="text" className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="e.g. Modern Pendant Light Black 30cm Adjustable Ceiling Lamp" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Bullet Points <span className="text-gray-400">(one per line)</span></label>
          <textarea rows={6} className="w-full border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" placeholder={"• Adjustable cord length\n• E27 fitting\n• Easy ceiling installation"} value={bulletsText} onChange={(e) => setBulletsText(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Description / A+ Content</label>
          <textarea rows={5} className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" placeholder="Paste the Amazon product description here..." value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Variant Terms to Strip <span className="text-gray-400">(comma separated)</span></label>
          <input type="text" className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="e.g. Black, White, Gold, 30cm, 45cm" value={variantsText} onChange={(e) => setVariantsText(e.target.value)} />
        </div>
        <div className="flex gap-3 pt-1">
          <button onClick={handleConvert} disabled={!title.trim() || loading} className="flex-1 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50 hover:bg-blue-700 transition-colors">
            {loading ? <span className="flex items-center justify-center gap-2"><svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" /></svg>Converting…</span> : 'Convert to Wayfair Format'}
          </button>
          <button onClick={handleClear} className="px-4 py-2.5 border border-gray-300 text-gray-600 rounded-lg text-sm hover:bg-gray-50 transition-colors">Clear</button>
        </div>
        {error && <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{error}</div>}
      </div>

      <div>
        {result ? <SingleResultPanel result={result} /> : (
          <div className="h-full flex items-center justify-center text-gray-400 border-2 border-dashed border-gray-200 rounded-lg min-h-64">
            <div className="text-center"><div className="text-4xl mb-3">✨</div><p className="text-sm">Converted content will appear here</p></div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Batch converter ───────────────────────────────────────────────────────────

function statusLabel(status: string) {
  if (status === 'valid') return <span className="text-green-700 font-medium">✓ Pass</span>
  if (status === 'requires_review') return <span className="text-yellow-700 font-medium">⚠ Review</span>
  if (status === 'no_sot_data') return <span className="text-gray-500">No data</span>
  return <span className="text-red-600 font-medium">Error</span>
}

function exportCsv(results: BatchItemResult[]) {
  const rows = results.map((r) => [
    r.asin,
    r.sku ?? '',
    r.product_name,
    r.marketing_copy,
    r.feature_bullets[0] ?? '',
    r.feature_bullets[1] ?? '',
    r.feature_bullets[2] ?? '',
    r.feature_bullets[3] ?? '',
    r.feature_bullets[4] ?? '',
    r.status,
    r.validation_errors.join('; '),
  ])
  const header = ['ASIN', 'SKU', 'Product Name', 'Marketing Copy', 'Bullet 1', 'Bullet 2', 'Bullet 3', 'Bullet 4', 'Bullet 5', 'Status', 'Validation Errors']
  const csv = [header, ...rows].map((row) => row.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'wayfair_content_batch.csv'; a.click()
  URL.revokeObjectURL(url)
}

function BatchRowDetail({ row }: { row: BatchItemResult }) {
  const [open, setOpen] = useState(false)
  const bulletsText = row.feature_bullets.map((b) => `• ${b}`).join('\n')

  return (
    <>
      <tr
        className={`cursor-pointer hover:bg-gray-50 ${row.status === 'error' || row.status === 'no_sot_data' ? 'bg-red-50' : row.status === 'requires_review' ? 'bg-yellow-50' : ''}`}
        onClick={() => setOpen((o) => !o)}
      >
        <td className="px-3 py-2 font-mono text-xs text-gray-700">{row.asin}</td>
        <td className="px-3 py-2 font-mono text-xs text-gray-500">{row.sku ?? '—'}</td>
        <td className="px-3 py-2 text-sm text-gray-800 max-w-xs truncate">{row.product_name || <span className="text-gray-400 italic">{row.error ?? 'No content'}</span>}</td>
        <td className="px-3 py-2 text-xs">{statusLabel(row.status)}</td>
        <td className="px-3 py-2 text-xs text-blue-500 select-none">{open ? '▲' : '▼'}</td>
      </tr>
      {open && row.product_name && (
        <tr className="bg-gray-50 border-t border-gray-100">
          <td colSpan={5} className="px-4 py-4">
            <div className="space-y-3 max-w-3xl">
              <div>
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-xs font-semibold text-gray-500 uppercase">Product Name</span>
                  <CopyButton text={row.product_name} />
                </div>
                <p className="text-sm text-gray-900">{row.product_name}</p>
              </div>
              <div>
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-xs font-semibold text-gray-500 uppercase">Marketing Copy <span className="font-normal normal-case text-gray-400">({row.marketing_copy_word_count}w)</span></span>
                  <CopyButton text={row.marketing_copy} />
                </div>
                <p className="text-sm text-gray-900 leading-relaxed">{row.marketing_copy}</p>
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-semibold text-gray-500 uppercase">Feature Bullets</span>
                  <CopyButton text={bulletsText} />
                </div>
                <ul className="space-y-0.5">
                  {row.feature_bullets.map((b, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-900">
                      <span className="text-gray-400 select-none">•</span>
                      <span>{b}</span>
                      <span className="ml-auto text-xs text-gray-400">{b.split(' ').length}w</span>
                    </li>
                  ))}
                </ul>
              </div>
              {row.validation_errors.length > 0 && (
                <div className="bg-yellow-50 border border-yellow-200 rounded p-2">
                  {row.validation_errors.map((e, i) => <p key={i} className="text-xs text-yellow-800">• {e}</p>)}
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function buildEdits(results: BatchItemResult[]): Record<string, string> {
  const edits: Record<string, string> = {}
  for (const r of results) {
    if (!r.product_name) continue
    const a = r.asin
    edits[`${a}::Product Name`] = r.product_name
    edits[`${a}::Marketing Copy`] = r.marketing_copy
    r.feature_bullets.forEach((b, i) => {
      edits[`${a}::Feature Bullet ${i + 1}`] = b
    })
  }
  return edits
}

function BatchTab() {
  const { runId, setRunId, setManualEdit, previewRows, previewHeaders, setPreviewRows, batchResponse: response, setBatchResponse: setResponse, batchAsinText: asinText, setBatchAsinText: setAsinText, autoRunBatch, setAutoRunBatch } = useRunStore()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [applied, setApplied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [applyError, setApplyError] = useState<string | null>(null)

  const parseAsins = (text: string) =>
    text.split(/[\n,\s]+/).map((a) => a.trim().toUpperCase()).filter((a) => a.length >= 8)

  // Auto-trigger when navigated from ASINs page
  React.useEffect(() => {
    if (autoRunBatch && asinText.trim() && !loading) {
      setAutoRunBatch(false)
      handleBatch()
    }
  }, [autoRunBatch]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleBatch = async () => {
    const asins = parseAsins(asinText)
    if (!asins.length) return
    setLoading(true); setError(null); setApplied(false)
    setResponse(null)
    const streamingResults: BatchItemResult[] = []
    try {
      const res = await batchConvert(asins, (item) => {
        streamingResults.push(item)
        const converted = streamingResults.filter((r) => r.status === 'valid' || r.status === 'requires_review').length
        const errors = streamingResults.filter((r) => r.status === 'error' || r.status === 'no_sot_data').length
        setResponse({ total: asins.length, converted, errors, results: [...streamingResults] })
      })
      setResponse(res)
      // Auto-apply to active run so Preview reflects it immediately
      if (runId && res.results.some((r) => r.product_name)) {
        const edits = buildEdits(res.results)
        const products = res.results.filter((r) => r.product_name).map((r) => ({ asin: r.asin, sku: r.sku, product_name: r.product_name }))
        try {
          await patchValues(runId, edits, products)
          Object.entries(edits).forEach(([k, v]) => setManualEdit(k, v))
          if (previewRows.length > 0) {
            const updatedRows = previewRows.map((row) => {
              const updatedCells = { ...row.cells }
              Object.entries(edits).forEach(([key, val]) => {
                const [editAsin, ...headerParts] = key.split('::')
                if (editAsin === row.asin) updatedCells[headerParts.join('::')] = { value: val, status: 'manual' }
              })
              return { ...row, cells: updatedCells }
            })
            setPreviewRows(updatedRows, previewHeaders)
          }
          setApplied(true)
        } catch { /* silent */ }
      }
    } catch (e) { setError((e as Error).message) }
    finally { setLoading(false) }
  }

  const handleApplyToRun = async () => {
    if (!response) return
    const edits = buildEdits(response.results)
    if (!Object.keys(edits).length) return
    const products = response.results
      .filter((r) => r.product_name)
      .map((r) => ({ asin: r.asin, sku: r.sku, product_name: r.product_name }))
    setApplying(true); setApplyError(null)
    try {
      let activeRunId = runId
      if (!activeRunId) {
        const { run_id } = await createRun()
        setRunId(run_id)
        activeRunId = run_id
      }
      try {
        await patchValues(activeRunId, edits, products)
      } catch (err: any) {
        const is404 = err?.response?.status === 404 || /not found/i.test(err?.message ?? '')
        if (is404) {
          const { run_id } = await createRun()
          setRunId(run_id)
          activeRunId = run_id
          await patchValues(activeRunId, edits, products)
        } else {
          throw err
        }
      }
      // Pull all SOT fields (EAN, weight, images, etc.) into the run
      try {
        await sotFill(activeRunId)
        setPreviewRows([], [])  // force Preview page to re-fetch with updated SOT data
      } catch { /* non-fatal — content is already saved */ }

      // Mirror into local Zustand store
      Object.entries(edits).forEach(([k, v]) => setManualEdit(k, v))
      // Patch cached preview rows so Preview page reflects changes without a re-fetch
      if (previewRows.length > 0) {
        const updatedRows = previewRows.map((row) => {
          const asin = row.asin
          const updatedCells = { ...row.cells }
          Object.entries(edits).forEach(([key, val]) => {
            const [editAsin, ...headerParts] = key.split('::')
            if (editAsin === asin) {
              const header = headerParts.join('::')
              updatedCells[header] = { value: val, status: 'manual' }
            }
          })
          return { ...row, cells: updatedCells }
        })
        setPreviewRows(updatedRows, previewHeaders)
      }
      setApplied(true)
    } catch (e) { setApplyError((e as Error).message) }
    finally { setApplying(false) }
  }

  const asins = parseAsins(asinText)
  const successRows = response?.results.filter((r) => r.product_name) ?? []
  const appliedCount = successRows.length

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        <div className="lg:col-span-1 space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              ASINs <span className="text-gray-400">(one per line, max 50)</span>
            </label>
            <textarea
              rows={12}
              className="w-full border rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              placeholder={"B001EXAMPLE1\nB002EXAMPLE2\nB003EXAMPLE3"}
              value={asinText}
              onChange={(e) => { setAsinText(e.target.value); setResponse(null); setApplied(false) }}
            />
            <p className="text-xs text-gray-400 mt-1">{asins.length} ASIN{asins.length !== 1 ? 's' : ''} detected</p>
          </div>

          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-xs text-blue-700">
            Content is fetched from the SOT database. ASINs not in SOT will show "No data".
          </div>

          <button
            onClick={handleBatch}
            disabled={asins.length === 0 || loading}
            className="w-full py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50 hover:bg-blue-700 transition-colors"
          >
            {loading
              ? <span className="flex items-center justify-center gap-2"><svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" /></svg>Converting {asins.length} ASINs…</span>
              : `Batch Convert ${asins.length || ''} ASINs`}
          </button>

          {/* Apply to Run — only shown when there's an active run and results */}
          {response && successRows.length > 0 && (
            <div className="space-y-2">
              {runId ? (
                <>
                  <button
                    onClick={handleApplyToRun}
                    disabled={applying || applied}
                    className={`w-full py-2.5 rounded-lg text-sm font-medium transition-colors ${
                      applied
                        ? 'bg-green-100 text-green-700 cursor-default'
                        : 'bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50'
                    }`}
                  >
                    {applying
                      ? <span className="flex items-center justify-center gap-2"><svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" /></svg>Applying…</span>
                      : applied
                      ? `✓ Applied ${appliedCount} product${appliedCount !== 1 ? 's' : ''} to run`
                      : `Apply ${appliedCount} product${appliedCount !== 1 ? 's' : ''} to Export Run`}
                  </button>
                  {applied && (
                    <div className="flex gap-2">
                      <button
                        onClick={() => navigate('/preview')}
                        className="flex-1 py-2 bg-white border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
                      >
                        View in Preview →
                      </button>
                      <button
                        onClick={() => navigate('/export')}
                        className="flex-1 py-2 bg-white border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
                      >
                        Go to Export →
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <button
                  onClick={handleApplyToRun}
                  disabled={applying}
                  className="w-full py-2.5 bg-purple-600 text-white rounded-lg text-sm font-medium hover:bg-purple-700 disabled:opacity-50 transition-colors"
                >
                  {applying ? 'Creating run…' : `Apply ${appliedCount} product${appliedCount !== 1 ? 's' : ''} to Export Run`}
                </button>
              )}
              {applyError && <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700">{applyError}</div>}
            </div>
          )}

          {error && <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{error}</div>}
        </div>

        <div className="lg:col-span-2">
          {response ? (
            <div className="space-y-4">
              {/* Summary bar */}
              <div className="flex items-center gap-4 text-sm">
                <span className="text-gray-600">Total: <strong>{response.total}</strong></span>
                <span className="text-green-700">Converted: <strong>{response.converted}</strong></span>
                {response.errors > 0 && <span className="text-red-600">Errors: <strong>{response.errors}</strong></span>}
                {successRows.length > 0 && (
                  <button
                    onClick={() => exportCsv(response.results)}
                    className="ml-auto px-3 py-1.5 bg-green-600 text-white rounded-lg text-xs font-medium hover:bg-green-700"
                  >
                    Export CSV
                  </button>
                )}
              </div>

              {/* Results table */}
              <div className="overflow-x-auto rounded-lg border border-gray-200">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">ASIN</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">SKU</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Product Name</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">QC</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {response.results.map((row) => (
                      <BatchRowDetail key={row.asin} row={row} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-gray-400 border-2 border-dashed border-gray-200 rounded-lg">
              <div className="text-center"><div className="text-4xl mb-3">📋</div><p className="text-sm">Results will appear here</p></div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Page shell ────────────────────────────────────────────────────────────────

type Tab = 'single' | 'batch'

export function ContentConverterPage() {
  const [tab, setTab] = useState<Tab>('batch')

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Content Converter</h1>
        <p className="text-sm text-gray-500 mt-1">
          Convert Amazon listing content into Wayfair Product Name, Marketing Copy, and Feature Bullets
        </p>
      </div>

      <div className="flex gap-2">
        {(['batch', 'single'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium capitalize ${
              tab === t ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            {t === 'batch' ? 'Batch by ASIN' : 'Single Product'}
          </button>
        ))}
      </div>

      {tab === 'single' ? <SingleTab /> : <BatchTab />}
    </div>
  )
}
