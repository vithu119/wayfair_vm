import React, { useEffect, useRef, useState } from 'react'
import { FileDropzone } from '../components/FileDropzone'
import { StatusBadge } from '../components/StatusBadge'
import { TemplateDetails } from '../components/TemplateDetails'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import { useRunStore } from '../store/runStore'
import { uploadTemplates, listTemplates, getTemplate, activateTemplate, deleteTemplate, deleteAllTemplates } from '../api/templates'
import type { TemplateEntry } from '../types'

interface UploadState {
  file: string
  status: 'uploading' | 'done' | 'error'
  error?: string
}

interface UploadResult {
  filename: string
  fill_status: string
  blocking_reasons: string[]
  error?: string | null
}

const ANALYSIS_STAGES = [
  'Uploading file…',
  'Inspecting workbook structure…',
  'Detecting listing sheet and headers…',
  'Classifying rows…',
  'Writing profile…',
  'Registering template…',
]

export function TemplatesPage() {
  const { uploadedTemplates, addTemplate, setTemplates, removeTemplate, approveTemplate, revokeApproval, sessionApprovedTemplates, resetDownstream } = useRunStore()
  const [uploading, setUploading] = useState<UploadState[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<TemplateEntry | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [analysisElapsed, setAnalysisElapsed] = useState(0)
  const [analysisStage, setAnalysisStage] = useState(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadTemplates = async () => {
    setLoading(true)
    try {
      const list = await listTemplates()
      if (list.length > 0) {
        const serverIds = new Set(list.map((t: TemplateEntry) => t.template_id))
        const localOnly = uploadedTemplates.filter((t) => !serverIds.has(t.template_id))
        // Fetch profiles for server templates that don't have one cached locally
        const withProfiles = await Promise.all(
          list.map(async (t: TemplateEntry) => {
            const cached = uploadedTemplates.find((c) => c.template_id === t.template_id)
            if (cached?.profile) return { ...t, profile: cached.profile }
            try {
              const full = await getTemplate(t.template_id)
              return { ...t, profile: full.profile }
            } catch {
              return t
            }
          })
        )
        setTemplates([...withProfiles, ...localOnly])
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadTemplates() }, [])

  const startAnalysisTimer = () => {
    setAnalysisElapsed(0)
    setAnalysisStage(0)
    timerRef.current = setInterval(() => {
      setAnalysisElapsed((s) => {
        const next = s + 1
        // Advance stage roughly every 4 seconds, capped at last stage
        setAnalysisStage(Math.min(Math.floor(next / 4), ANALYSIS_STAGES.length - 1))
        return next
      })
    }, 1000)
  }

  const stopAnalysisTimer = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }

  const handleFiles = async (files: File[]) => {
    const states: UploadState[] = files.map((f) => ({ file: f.name, status: 'uploading' }))
    setUploading(states)
    startAnalysisTimer()
    try {
      const results: UploadResult[] = await uploadTemplates(files)
      stopAnalysisTimer()
      setUploading(
        files.map((f) => {
          const result = results.find((r) => r.filename === f.name)
          const serverError = result?.error ?? (result?.blocking_reasons?.length ? result.blocking_reasons.join('; ') : undefined)
          return serverError
            ? { file: f.name, status: 'error', error: serverError }
            : { file: f.name, status: 'done' }
        })
      )
      resetDownstream()
      await loadTemplates()
    } catch (e) {
      stopAnalysisTimer()
      setUploading(files.map((f) => ({ file: f.name, status: 'error', error: (e as Error).message })))
    }
  }

  const handleRowClick = async (entry: TemplateEntry) => {
    try {
      const full = await getTemplate(entry.template_id)
      setSelected(full)
    } catch {
      setSelected(entry)
    }
  }

  const handleActivate = async (e: React.MouseEvent, tid: string) => {
    e.stopPropagation()
    try {
      await activateTemplate(tid)
      await loadTemplates()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Templates</h1>
        <p className="text-sm text-gray-500 mt-1">Upload and manage Wayfair listing templates</p>
      </div>

      <FileDropzone
        accept={['xlsx', 'csv']}
        onFiles={handleFiles}
        label="Drop Wayfair template files here (.xlsx or .csv)"
      />

      {uploading.length > 0 && (
        <div className="space-y-2">
          {uploading.map((u, i) => (
            <div key={i}>
              <div className="flex items-center gap-2 text-sm">
                {u.status === 'uploading' && <LoadingSpinner size="sm" />}
                {u.status === 'done' && <span className="text-green-600">✓</span>}
                {u.status === 'error' && <span className="text-red-600">✗</span>}
                <span>{u.file}</span>
                {u.status === 'uploading' && (
                  <span className="text-xs text-gray-400">{analysisElapsed}s</span>
                )}
                {u.error && <span className="text-red-500 text-xs">{u.error}</span>}
              </div>
              {u.status === 'uploading' && (
                <div className="mt-1 ml-6">
                  <div className="flex items-center gap-2 mb-1">
                    <div className="h-1.5 flex-1 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500 rounded-full transition-all duration-1000"
                        style={{ width: `${Math.min(((analysisStage + 1) / ANALYSIS_STAGES.length) * 100, 95)}%` }}
                      />
                    </div>
                  </div>
                  <p className="text-xs text-gray-500">{ANALYSIS_STAGES[analysisStage]}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>
      )}

      {loading && <LoadingSpinner message="Loading templates..." />}

      {!loading && uploadedTemplates.length === 0 && (
        <EmptyState
          icon="📋"
          title="No templates yet"
          message="Upload Wayfair listing template files to get started"
        />
      )}

      {uploadedTemplates.length > 0 && (
        <div className="flex justify-end">
          <button
            onClick={async () => {
              try {
                await deleteAllTemplates()
              } catch { /* best-effort */ }
              setTemplates([])
              resetDownstream()
            }}
            className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 transition-colors"
          >
            Clear All Templates
          </button>
        </div>
      )}

      {uploadedTemplates.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="w-full text-sm" data-testid="template-table">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">File</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Category</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Purpose</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Fill Status</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Listing Sheet</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Issues</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {uploadedTemplates.map((entry) => (
                <React.Fragment key={entry.template_id}>
                  {entry.fill_status === 'requires_review' && (
                    <tr className="bg-amber-50">
                      <td colSpan={7} className="px-3 py-2">
                        <div className="flex items-center justify-between">
                          <span className="text-xs text-amber-700 font-medium">
                            ⚠ This template requires review before use
                          </span>
                          <label className="flex items-center gap-1 text-xs text-amber-700 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={sessionApprovedTemplates.has(entry.template_id)}
                              onChange={(e) =>
                                e.target.checked
                                  ? approveTemplate(entry.template_id)
                                  : revokeApproval(entry.template_id)
                              }
                            />
                            Approve for this session
                          </label>
                        </div>
                      </td>
                    </tr>
                  )}
                  <tr
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() => handleRowClick(entry)}
                  >
                    <td className="px-3 py-2 font-medium truncate max-w-xs">{entry.filename}</td>
                    <td className="px-3 py-2 text-gray-600">{entry.category}</td>
                    <td className="px-3 py-2"><StatusBadge status={entry.template_purpose} /></td>
                    <td className="px-3 py-2"><StatusBadge status={entry.fill_status} /></td>
                    <td className="px-3 py-2 text-gray-600">{entry.listing_sheet ?? '—'}</td>
                    <td className="px-3 py-2">
                      <span className={`text-xs ${entry.blocking_reasons.length ? 'text-red-600' : 'text-gray-400'}`}>
                        {entry.blocking_reasons.length + entry.warnings.length} issue(s)
                      </span>
                    </td>
                    <td className="px-3 py-2 flex items-center gap-3">
                      {!entry.is_active && (
                        <button
                          onClick={(e) => handleActivate(e, entry.template_id)}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          Activate
                        </button>
                      )}
                      <button
                        onClick={async (e) => {
                          e.stopPropagation()
                          try { await deleteTemplate(entry.template_id) } catch { /* best-effort */ }
                          removeTemplate(entry.template_id)
                        }}
                        className="text-xs text-red-500 hover:underline"
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <TemplateDetails template={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
