import React, { useState } from 'react'
import { useRunStore } from '../store/runStore'
import { validateRun, getFindings } from '../api/runs'
import { FilterBar } from '../components/FilterBar'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import type { ValidationFinding } from '../types'

const SEVERITY_ORDER = ['blocking', 'error', 'warning', 'review', 'info']

export function ValidationPage() {
  const { runId, findings, setFindings } = useRunStore()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('all')

  const handleRevalidate = async () => {
    if (!runId) {
      setError('No active run. Process products first.')
      return
    }
    setLoading(true)
    setError(null)
    setFindings([])
    try {
      await validateRun(runId)
      const grouped = await getFindings(runId)
      const all: ValidationFinding[] = [
        ...(grouped.blocking ?? []),
        ...(grouped.error ?? []),
        ...(grouped.warning ?? []),
        ...(grouped.review ?? []),
        ...(grouped.info ?? []),
      ]
      setFindings(all)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const counts = SEVERITY_ORDER.reduce<Record<string, number>>((acc, sev) => {
    acc[sev] = findings.filter((f) => f.severity === sev).length
    return acc
  }, {})

  const filtered = filter === 'all'
    ? findings
    : findings.filter((f) => f.severity === filter)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Validation</h1>
          <p className="text-sm text-gray-500 mt-1">Review issues before export</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleRevalidate}
            disabled={loading || !runId}
            data-testid="revalidate-btn"
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm disabled:opacity-50"
          >
            {loading ? 'Validating...' : 'Revalidate All'}
          </button>
          <button
            disabled={!findings.length}
            onClick={() => {
              const header = ['ASIN', 'SKU', 'Column', 'Value', 'Severity', 'Error Type', 'Recommended Action']
              const rows = findings.map((f) => [
                f.asin, f.sku ?? '', f.column, f.value ?? '', f.severity, f.error_type, f.recommended_action,
              ])
              const csv = [header, ...rows]
                .map((row) => row.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(','))
                .join('\n')
              const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url; a.download = 'validation_report.csv'; a.click()
              URL.revokeObjectURL(url)
            }}
            className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm disabled:opacity-50 hover:bg-gray-200 transition-colors"
          >
            Export Validation Report
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>
      )}

      {loading && <LoadingSpinner message="Validating products..." />}

      {/* Severity summary */}
      <div className="grid grid-cols-5 gap-3" data-testid="severity-summary">
        {SEVERITY_ORDER.map((sev) => (
          <div key={sev} className="bg-white border rounded-lg p-3 text-center">
            <StatusBadge status={sev} />
            <p className="text-2xl font-bold mt-1">{counts[sev] ?? 0}</p>
          </div>
        ))}
      </div>

      {findings.length > 0 ? (
        <div className="space-y-3">
          <FilterBar
            options={[
              { key: 'all', label: 'All', count: findings.length },
              ...SEVERITY_ORDER.map((s) => ({ key: s, label: s, count: counts[s] ?? 0 })),
            ]}
            active={filter}
            onChange={setFilter}
          />

          <div className="overflow-x-auto rounded-lg border border-gray-200" data-testid="findings-table">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">ASIN</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">SKU</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Column</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Value</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Severity</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Error Type</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Recommended Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.map((f, i) => (
                  <tr key={i} className={f.severity === 'blocking' ? 'bg-red-50' : ''}>
                    <td className="px-3 py-2 font-mono text-xs">{f.asin}</td>
                    <td className="px-3 py-2 text-xs">{f.sku ?? '—'}</td>
                    <td className="px-3 py-2 text-xs">{f.column}</td>
                    <td className="px-3 py-2 text-xs truncate max-w-xs">{f.value || '—'}</td>
                    <td className="px-3 py-2"><StatusBadge status={f.severity} /></td>
                    <td className="px-3 py-2 text-xs">{f.error_type}</td>
                    <td className="px-3 py-2 text-xs text-gray-600">{f.recommended_action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        !loading && (
          <EmptyState
            icon="✅"
            title="No validation findings"
            message={runId ? "Click Revalidate All to check products" : "Process products first, then validate"}
          />
        )
      )}
    </div>
  )
}
