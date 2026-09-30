import client from './client'

export interface ConvertRequest {
  group_ref_id?: string
  amazon_title: string
  amazon_bullets: string[]
  amazon_description: string
  variant_terms: string[]
}

export interface ConvertResponse {
  group_ref_id: string
  product_name: string
  marketing_copy: string
  marketing_copy_word_count: number
  feature_bullets: string[]
  status: 'valid' | 'requires_review' | 'error'
  validation_errors: string[]
  qc_pass: boolean
}

export async function convertContent(req: ConvertRequest): Promise<ConvertResponse> {
  const { data } = await client.post<ConvertResponse>('/content/convert', req)
  return data
}

export interface BatchItemResult {
  asin: string
  sku: string | null
  group_ref_id: string
  product_name: string
  marketing_copy: string
  marketing_copy_word_count: number
  feature_bullets: string[]
  status: 'valid' | 'requires_review' | 'error' | 'no_sot_data'
  validation_errors: string[]
  variant_terms: string[]
  qc_pass: boolean
  error: string | null
}

export interface BatchResponse {
  total: number
  converted: number
  errors: number
  results: BatchItemResult[]
}

export async function batchConvert(
  asins: string[],
  onResult?: (item: BatchItemResult) => void,
): Promise<BatchResponse> {
  const stored = localStorage.getItem('wayfair-auth')
  let token = ''
  try {
    if (stored) token = JSON.parse(stored)?.state?.token ?? ''
  } catch { /* ignore */ }

  const response = await fetch('/api/content/batch/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ asins }),
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(err.detail ?? 'Batch convert failed')
  }

  const results: BatchItemResult[] = []
  let total = asins.length, converted = 0, errors = 0

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const event = JSON.parse(line.slice(6))
      if (event.type === 'result') {
        const item: BatchItemResult = event
        results.push(item)
        onResult?.(item)
      } else if (event.type === 'done') {
        total = event.total
        converted = event.converted
        errors = event.errors
      }
    }
  }

  return { total, converted, errors, results }
}
