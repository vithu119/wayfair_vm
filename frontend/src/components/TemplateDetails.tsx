import React from 'react'
import type { TemplateEntry } from '../types'
import { StatusBadge } from './StatusBadge'

interface Props {
  template: TemplateEntry | null
  onClose: () => void
}

export function TemplateDetails({ template, onClose }: Props) {
  if (!template) return null

  const profile = template.profile as Record<string, unknown> | undefined
  const exactHeaders: string[] = Array.isArray(profile?.exact_headers)
    ? (profile!.exact_headers as string[])
    : []
  const warnings: string[] = Array.isArray(template.warnings)
    ? template.warnings
    : typeof template.warnings === 'string' && template.warnings
      ? (template.warnings as unknown as string).split(' | ').filter(Boolean)
      : []
  const blockingReasons: string[] = Array.isArray(template.blocking_reasons)
    ? template.blocking_reasons
    : typeof template.blocking_reasons === 'string' && template.blocking_reasons
      ? (template.blocking_reasons as unknown as string).split(' | ').filter(Boolean)
      : []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-lg font-semibold">Template Details</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <div className="overflow-y-auto p-4 space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><span className="font-medium text-gray-500">Filename:</span> <span>{template.filename}</span></div>
            <div><span className="font-medium text-gray-500">Category:</span> <span>{template.category}</span></div>
            <div><span className="font-medium text-gray-500">Fill Status:</span> <StatusBadge status={template.fill_status} /></div>
            <div><span className="font-medium text-gray-500">Purpose:</span> <StatusBadge status={template.template_purpose} /></div>
            <div><span className="font-medium text-gray-500">Listing Sheet:</span> <span>{template.listing_sheet ?? 'N/A'}</span></div>
            <div><span className="font-medium text-gray-500">Header Row:</span> <span>{template.header_row ?? 'N/A'}</span></div>
            <div><span className="font-medium text-gray-500">Safe Write Start:</span> <span>{template.safe_write_start_row ?? 'N/A'}</span></div>
            <div><span className="font-medium text-gray-500">Template ID:</span> <span className="font-mono text-xs">{template.template_id}</span></div>
          </div>

          {warnings.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-yellow-700 mb-1">Warnings</h3>
              <ul className="text-xs text-yellow-700 space-y-1 list-disc list-inside">
                {warnings.map((w, i) => <li key={i} className="bg-yellow-50 rounded px-2 py-1">{w}</li>)}
              </ul>
            </div>
          )}

          {blockingReasons.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-red-700 mb-1">Blocking Reasons</h3>
              <ul className="text-xs text-red-700 space-y-1 list-disc list-inside">
                {blockingReasons.map((r, i) => <li key={i} className="bg-red-50 rounded px-2 py-1">{r}</li>)}
              </ul>
            </div>
          )}

          {!profile && (
            <p className="text-xs text-gray-400 italic">
              Profile not available — re-upload the template to refresh.
            </p>
          )}

          {profile && exactHeaders.length === 0 && (
            <p className="text-xs text-gray-400 italic">No column headers detected in listing sheet.</p>
          )}

          {exactHeaders.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">Template Headers ({exactHeaders.length})</h3>
              <div className="max-h-64 overflow-y-auto border rounded">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 sticky top-0">
                    <tr>
                      <th className="px-2 py-1 text-left text-gray-500">#</th>
                      <th className="px-2 py-1 text-left text-gray-500">Header</th>
                    </tr>
                  </thead>
                  <tbody>
                    {exactHeaders.map((h, i) => (
                      <tr key={i} className="border-t">
                        <td className="px-2 py-1 text-gray-400">{i + 1}</td>
                        <td className="px-2 py-1">{h}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
        <div className="p-4 border-t flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded bg-gray-100 hover:bg-gray-200"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
