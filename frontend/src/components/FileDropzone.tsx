import React, { useCallback, useState } from 'react'

interface Props {
  accept?: string[]
  multiple?: boolean
  onFiles: (files: File[]) => void
  label?: string
  disabled?: boolean
}

export function FileDropzone({ accept, multiple = true, onFiles, label, disabled }: Props) {
  const [dragging, setDragging] = useState(false)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragging(false)
      if (disabled) return
      const files = Array.from(e.dataTransfer.files)
      const filtered = accept
        ? files.filter((f) => accept.some((ext) => f.name.toLowerCase().endsWith(ext)))
        : files
      if (filtered.length) onFiles(filtered)
    },
    [accept, disabled, onFiles]
  )

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || [])
      if (files.length) onFiles(files)
      e.target.value = ''
    },
    [onFiles]
  )

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
        dragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <p className="text-sm text-gray-600 mb-2">
        {label ?? 'Drop files here or click to browse'}
      </p>
      {accept && (
        <p className="text-xs text-gray-400">Accepted: {accept.join(', ')}</p>
      )}
      <label className="mt-3 inline-block">
        <span className="sr-only">Choose files</span>
        <input
          type="file"
          className="hidden"
          multiple={multiple}
          accept={accept?.map((e) => `.${e}`).join(',')}
          onChange={handleChange}
          disabled={disabled}
        />
        <span className="text-blue-600 text-sm underline cursor-pointer">Browse files</span>
      </label>
    </div>
  )
}
