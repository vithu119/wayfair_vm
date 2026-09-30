import React, { useState } from 'react'

interface Props {
  value: string
  options?: string[]
  onSave: (value: string) => void
  disabled?: boolean
}

export function CellEditor({ value, options, onSave, disabled }: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)

  if (!editing) {
    return (
      <div
        className="min-w-0 cursor-pointer hover:bg-gray-50 px-1 py-0.5 rounded text-xs truncate"
        onClick={() => !disabled && setEditing(true)}
        title={value || '(empty)'}
      >
        {value || <span className="text-gray-300">—</span>}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1 min-w-0">
      {options && options.length > 0 ? (
        <select
          className="text-xs border rounded px-1 py-0.5 flex-1 min-w-0"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          autoFocus
        >
          <option value="">— select —</option>
          {options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : (
        <input
          className="text-xs border rounded px-1 py-0.5 flex-1 min-w-0"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          autoFocus
          onKeyDown={(e) => {
            if (e.key === 'Enter') { onSave(draft); setEditing(false) }
            if (e.key === 'Escape') { setDraft(value); setEditing(false) }
          }}
        />
      )}
      <button
        className="text-xs text-blue-600 hover:text-blue-800 px-1"
        onClick={() => { onSave(draft); setEditing(false) }}
      >✓</button>
      <button
        className="text-xs text-gray-400 hover:text-gray-600 px-1"
        onClick={() => { setDraft(value); setEditing(false) }}
      >✕</button>
    </div>
  )
}
