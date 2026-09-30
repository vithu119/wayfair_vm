import React, { useState, useEffect, useRef } from 'react'
import { FileDropzone } from '../components/FileDropzone'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import { useRunStore } from '../store/runStore'
import { uploadCsv, uploadExcel, previewSource, getSotStatus } from '../api/sources'
import type { SourceFile } from '../types'

type SourceType = 'csv' | 'excel' | 'sot'

export function DataSourcesPage() {
  const { sourceFiles, addSource, removeSource } = useRunStore()
  const [activeType, setActiveType] = useState<SourceType>('sot')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewData, setPreviewData] = useState<{ sourceId: string; rows: Record<string, string>[] } | null>(null)
  const [sotStatus, setSotStatus] = useState<{ source: string; connected: boolean; read_only: boolean; error: string | null; approved_tables: string[] } | null>(null)
  const [sotLoading, setSotLoading] = useState(false)
  const [sotAdded, setSotAdded] = useState(false)

  const sotPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    const fetchStatus = (showLoading = false) => {
      if (showLoading) setSotLoading(true)
      getSotStatus()
        .then(setSotStatus)
        .catch((e) => setSotStatus({ source: 'Configurator SOT', connected: false, read_only: false, error: (e as Error).message, approved_tables: [] }))
        .finally(() => setSotLoading(false))
    }
    fetchStatus(true)
    sotPollRef.current = setInterval(() => fetchStatus(false), 60_000)
    return () => { if (sotPollRef.current) clearInterval(sotPollRef.current) }
  }, [])

  const handleCsvFiles = async (files: File[]) => {
    setUploading(true)
    setError(null)
    try {
      for (const file of files) {
        const result = await uploadCsv(file)
        addSource(result)
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setUploading(false)
    }
  }

  const handleExcelFile = async (files: File[]) => {
    setUploading(true)
    setError(null)
    try {
      const result = await uploadExcel(files[0])
      addSource(result)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setUploading(false)
    }
  }

  const handlePreview = async (sourceId: string) => {
    try {
      const data = await previewSource(sourceId)
      setPreviewData({ sourceId, rows: data.preview })
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const handleSotTabClick = async () => {
    setActiveType('sot')
    if (!sotStatus || sotStatus.error) {
      setSotLoading(true)
      try {
        const status = await getSotStatus()
        setSotStatus(status)
      } catch (e) {
        setSotStatus({ source: 'Configurator SOT', connected: false, read_only: false, error: (e as Error).message, approved_tables: [] })
      } finally {
        setSotLoading(false)
      }
    }
  }

  const handleAddSotSource = () => {
    const virtualSource: SourceFile = {
      source_id: 'configurator_sot',
      filename: 'Configurator SOT',
      row_count: 0,
      columns: [],
      asin_column: null,
      sku_column: null,
      category_column: null,
      preview: [],
    }
    addSource(virtualSource)
    setSotAdded(true)
  }

  const handleRemoveSotSource = () => {
    removeSource('configurator_sot')
    setSotAdded(false)
  }

  // Sync sotAdded with persisted store on mount
  useEffect(() => {
    setSotAdded(sourceFiles.some((s) => s.source_id === 'configurator_sot'))
  }, [])

  const csvSources = sourceFiles.filter((s) => s.source_id !== 'configurator_sot' && s.filename.endsWith('.csv'))
  const excelSources = sourceFiles.filter((s) => s.source_id !== 'configurator_sot' && !s.filename.endsWith('.csv'))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Data Sources</h1>
        <p className="text-sm text-gray-500 mt-1">Upload product data files to populate templates</p>
      </div>

      <div className="flex gap-2">
        <button
          onClick={handleSotTabClick}
          className={`px-4 py-2 rounded-lg text-sm font-medium ${
            activeType === 'sot' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
        >
          Configurator SOT
        </button>
        {(['excel', 'csv'] as SourceType[]).map((t) => (
          <button
            key={t}
            onClick={() => setActiveType(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium ${
              activeType === t ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            {t === 'csv' ? 'CSV Upload' : 'Excel Upload'}
          </button>
        ))}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>
      )}

      {activeType === 'csv' && (
        <div className="space-y-4">
          <FileDropzone accept={['csv']} onFiles={handleCsvFiles} label="Drop CSV product data files here" />
          {uploading && <LoadingSpinner message="Uploading and parsing CSV..." />}
          {csvSources.length === 0 ? (
            <EmptyState icon="📄" title="No CSV sources" message="Upload a CSV file with product data" />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-200">
              <table className="w-full text-sm" data-testid="csv-table">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">File</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Rows</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">ASIN Column</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">SKU Column</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {csvSources.map((src) => (
                    <tr key={src.source_id}>
                      <td className="px-3 py-2 font-medium">{src.filename}</td>
                      <td className="px-3 py-2">{src.row_count}</td>
                      <td className="px-3 py-2">{src.asin_column ?? <span className="text-gray-400">—</span>}</td>
                      <td className="px-3 py-2">{src.sku_column ?? <span className="text-gray-400">—</span>}</td>
                      <td className="px-3 py-2 flex items-center gap-3">
                        <button
                          onClick={() => handlePreview(src.source_id)}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          Preview
                        </button>
                        <button
                          onClick={() => removeSource(src.source_id)}
                          className="text-xs text-red-500 hover:underline"
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeType === 'excel' && (
        <div className="space-y-4">
          <FileDropzone accept={['xlsx', 'xls']} multiple={false} onFiles={handleExcelFile} label="Drop Excel product data file here" />
          {uploading && <LoadingSpinner message="Uploading and parsing Excel..." />}
          {excelSources.length === 0 ? (
            <EmptyState icon="📊" title="No Excel sources" message="Upload an Excel file with product data" />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-200">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">File</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Sheet</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Rows</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {excelSources.map((src) => (
                    <tr key={src.source_id} data-testid="excel-row">
                      <td className="px-3 py-2 font-medium">{src.filename}</td>
                      <td className="px-3 py-2">
                        <select
                          className="text-xs border rounded px-1 py-0.5"
                          defaultValue={src.chosen_sheet ?? ''}
                          data-testid="sheet-selector"
                        >
                          {(src.sheet_names ?? []).map((s) => (
                            <option key={s} value={s}>{s}</option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-2">{src.row_count}</td>
                      <td className="px-3 py-2 flex items-center gap-3">
                        <button
                          onClick={() => handlePreview(src.source_id)}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          Preview
                        </button>
                        <button
                          onClick={() => removeSource(src.source_id)}
                          className="text-xs text-red-500 hover:underline"
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeType === 'sot' && (
        <div className="space-y-4">
          {sotLoading && <LoadingSpinner message="Checking Configurator SOT connection..." />}
          {sotStatus && (
            <div className="rounded-lg border border-gray-200 p-4 space-y-3">
              <div className="flex items-center gap-3">
                <span className="font-medium text-gray-800">{sotStatus.source}</span>
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                    sotStatus.connected ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                  }`}
                >
                  {sotStatus.connected ? 'Connected' : 'Not Connected'}
                </span>
                {sotStatus.connected && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
                    Read-only
                  </span>
                )}
              </div>

              {sotStatus.error && (
                <div className="bg-amber-50 border border-amber-200 rounded p-3 text-sm text-amber-800">
                  {sotStatus.error === 'configurator_sot_not_configured'
                    ? 'Configurator SOT database is not configured. Set the CONFIGURATOR_DB_* environment variables on the server.'
                    : 'Could not connect to Configurator SOT. Check server logs for details.'}
                </div>
              )}

              {sotStatus.approved_tables.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-1">Approved tables (read-only access)</p>
                  <ul className="space-y-0.5 list-disc list-inside">
                    {sotStatus.approved_tables.map((t) => (
                      <li key={t} className="text-xs text-gray-600 font-mono">{t}</li>
                    ))}
                  </ul>
                </div>
              )}

              {sotStatus.connected && (
                <div className="flex items-center gap-3">
                  {sotAdded ? (
                    <>
                      <span className="inline-flex items-center px-3 py-1.5 rounded-lg text-sm font-medium bg-green-100 text-green-700">
                        ✓ Added as data source
                      </span>
                      <button
                        onClick={handleRemoveSotSource}
                        className="px-3 py-1.5 rounded-lg text-sm font-medium bg-red-50 text-red-600 hover:bg-red-100 border border-red-200"
                      >
                        Remove
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={handleAddSotSource}
                      className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-700"
                    >
                      Use as data source
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
          {!sotLoading && !sotStatus && (
            <EmptyState icon="🗄️" title="Configurator SOT" message="Click the tab to check connection status" />
          )}
        </div>
      )}

      {/* Preview modal */}
      {previewData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b">
              <h2 className="text-lg font-semibold">Source Preview (first 20 rows)</h2>
              <button onClick={() => setPreviewData(null)} className="text-gray-400 hover:text-gray-600">&times;</button>
            </div>
            <div className="overflow-auto p-4">
              {previewData.rows.length === 0 ? (
                <p className="text-sm text-gray-500">No rows</p>
              ) : (
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="bg-gray-50">
                      {Object.keys(previewData.rows[0]).map((col) => (
                        <th key={col} className="border px-2 py-1 text-left font-medium text-gray-600 whitespace-nowrap">{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {previewData.rows.map((row, i) => (
                      <tr key={i} className="border-t hover:bg-gray-50">
                        {Object.values(row).map((v, j) => (
                          <td key={j} className="border px-2 py-1 truncate max-w-xs">{v}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
