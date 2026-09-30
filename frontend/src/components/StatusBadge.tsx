import React from 'react'

const STATUS_COLORS: Record<string, string> = {
  fillable: 'bg-green-100 text-green-800',
  fillable_with_warnings: 'bg-yellow-100 text-yellow-800',
  requires_review: 'bg-amber-100 text-amber-800',
  not_fillable: 'bg-red-100 text-red-800',
  failed: 'bg-red-100 text-red-800',
  uploading: 'bg-blue-100 text-blue-800',
  analysing: 'bg-blue-100 text-blue-800',
  registered: 'bg-purple-100 text-purple-800',
  matched: 'bg-green-100 text-green-800',
  unmatched: 'bg-red-100 text-red-800',
  ambiguous: 'bg-yellow-100 text-yellow-800',
  blocking: 'bg-red-100 text-red-800',
  error: 'bg-orange-100 text-orange-800',
  warning: 'bg-yellow-100 text-yellow-800',
  review: 'bg-blue-100 text-blue-800',
  info: 'bg-gray-100 text-gray-700',
  created: 'bg-gray-100 text-gray-700',
  resolved: 'bg-blue-100 text-blue-800',
  validated: 'bg-yellow-100 text-yellow-800',
  exported: 'bg-green-100 text-green-800',
}

interface Props {
  status: string
  label?: string
}

export function StatusBadge({ status, label }: Props) {
  const cls = STATUS_COLORS[status] ?? 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {label ?? status.replace(/_/g, ' ')}
    </span>
  )
}
