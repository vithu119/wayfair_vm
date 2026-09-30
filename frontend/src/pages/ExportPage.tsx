import React, { useState } from 'react'
import { useRunStore } from '../store/runStore'
import { exportRun, listDownloads } from '../api/runs'
import client from '../api/client'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import type { DownloadFile } from '../types'

export function ExportPage() {
  const { runId, uploadedTemplates, findings, exportFiles, setExports, setRunId, setTemplates } = useRunStore()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sessionLost, setSessionLost] = useState(false)
  const [downloads, setDownloads] = useState<DownloadFile[]>([])

  const blockingCount = findings.filter((f) => f.severity === 'blocking').length
  const hasBlocking = blockingCount > 0

  const handleExport = async () => {
    if (!runId) {
      setError('No active run. Process products first.')
      return
    }
    setLoading(true)
    setError(null)
    setSessionLost(false)
    try {
      const res = await exportRun(runId)
      setExports(res.export_files ?? [])
      const dl = await listDownloads(runId)
      setDownloads(dl)
    } catch (e: any) {
      if (e?.response?.status === 404) {
        setRunId(null)
        setTemplates([])
        setSessionLost(true)
      } else {
        setError(e?.response?.data?.detail ?? (e as Error).message)
      }
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = async (filename: string) => {
    try {
      const res = await client.get(`/runs/${runId}/downloads/${encodeURIComponent(filename)}`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  // Group downloads by template
  const byTemplate: Record<string, DownloadFile[]> = {}
  for (const dl of downloads) {
    const key = dl.template_id ?? 'unknown'
    ;(byTemplate[key] = byTemplate[key] ?? []).push(dl)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Export</h1>
          <p className="text-sm text-gray-500 mt-1">Download filled templates</p>
        </div>
        <button
          onClick={handleExport}
          disabled={loading || !runId}
          data-testid="export-btn"
          className="px-5 py-2 bg-green-600 text-white rounded-lg text-sm font-medium disabled:opacity-50 hover:bg-green-700 transition-colors"
        >
          {loading ? 'Exporting...' : 'Generate Exports'}
        </button>
      </div>

      {hasBlocking && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 flex items-start gap-3">
          <span className="text-yellow-500 text-lg">⚠️</span>
          <div>
            <p className="text-sm font-medium text-yellow-800">
              {blockingCount} blocking issue{blockingCount !== 1 ? 's' : ''} detected
            </p>
            <p className="text-xs text-yellow-700 mt-0.5">
              You can still export, but affected products may have missing required fields.
              Go to Validation to review them.
            </p>
          </div>
        </div>
      )}

      {sessionLost && (
        <div className="bg-orange-50 border border-orange-300 rounded-lg p-4 text-sm text-orange-800">
          <p className="font-semibold mb-1">Session data lost — server was restarted</p>
          <p className="text-xs mb-3">Your run data was cleared when the server restarted. Please start a new session:</p>
          <ol className="text-xs list-decimal ml-4 space-y-1">
            <li>Go to <strong>Templates</strong> and re-upload your template files</li>
            <li>Go to <strong>ASINs</strong> and process your products again</li>
            <li>Go to <strong>Preview</strong> and apply SOT data</li>
            <li>Return here and click Generate Exports</li>
          </ol>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>
      )}

      {loading && <LoadingSpinner message="Generating export files..." />}

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs text-blue-700">
        Original templates are never modified. All exports are written to new files in the run output folder.
      </div>

      {downloads.length > 0 ? (
        <div className="space-y-4">
          {Object.entries(byTemplate).map(([templateId, files]) => {
            const entry = uploadedTemplates.find((t) => t.template_id === templateId)
            const exportMeta = exportFiles.find((e) => e.template_id === templateId)
            return (
              <div key={templateId} className="border rounded-lg overflow-hidden">
                <div className="bg-gray-50 px-4 py-3 flex items-center justify-between">
                  <div>
                    <p className="font-medium text-sm">{entry?.category ?? templateId}</p>
                    <p className="text-xs text-gray-500">{entry?.filename ?? templateId}</p>
                  </div>
                  {exportMeta && (
                    <span className="text-xs text-gray-500">{exportMeta.product_count} product(s)</span>
                  )}
                </div>
                <div className="divide-y">
                  {files.map((dl) => (
                    <div key={dl.filename} className="flex items-center justify-between px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span className="text-lg">{dl.file_type === 'xlsx' ? '📊' : '📄'}</span>
                        <div>
                          <p className="text-sm font-medium">{dl.filename}</p>
                          <p className="text-xs text-gray-500">{formatBytes(dl.size_bytes)} · {dl.file_type.toUpperCase()}</p>
                        </div>
                      </div>
                      <button
                        onClick={() => handleDownload(dl.filename)}
                        data-testid="download-btn"
                        className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700"
                      >
                        Download
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        !loading && (
          <EmptyState
            icon="📦"
            title="No exports yet"
            message="Click Generate Exports to create download files"
          />
        )
      )}
    </div>
  )
}
