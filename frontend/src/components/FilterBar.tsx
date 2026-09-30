import React from 'react'

interface FilterOption {
  key: string
  label: string
  count?: number
}

interface Props {
  options: FilterOption[]
  active: string
  onChange: (key: string) => void
}

export function FilterBar({ options, active, onChange }: Props) {
  return (
    <div className="flex flex-wrap gap-1">
      {options.map((opt) => (
        <button
          key={opt.key}
          onClick={() => onChange(opt.key)}
          className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
            active === opt.key
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
        >
          {opt.label}
          {opt.count !== undefined && (
            <span className="ml-1 opacity-75">({opt.count})</span>
          )}
        </button>
      ))}
    </div>
  )
}
