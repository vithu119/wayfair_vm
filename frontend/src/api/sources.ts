import client from './client'
import type { SourceFile } from '../types'

export const uploadCsv = async (file: File): Promise<SourceFile> => {
  const form = new FormData()
  form.append('file', file)
  const res = await client.post('/sources/csv/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

export const uploadExcel = async (file: File, sheet?: string): Promise<SourceFile> => {
  const form = new FormData()
  form.append('file', file)
  const params = sheet ? { sheet } : {}
  const res = await client.post('/sources/excel/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    params,
  })
  return res.data
}

export const previewSource = async (sourceId: string) => {
  const res = await client.get(`/sources/${sourceId}/preview`)
  return res.data
}

export async function getSotStatus(): Promise<{
  source: string
  connected: boolean
  read_only: boolean
  error: string | null
  approved_tables: string[]
}> {
  const res = await client.get('/sot/status')
  return res.data
}

export async function resolveAsinsSot(asins: string[]): Promise<{ results: SotResolutionResult[] }> {
  const res = await client.post('/sot/resolve', { asins })
  return res.data
}

export interface SotResolutionResult {
  input_asin: string
  asin: string | null
  primary_sku: string | null
  component_skus: string[]
  source_tab: string | null
  product_subtype: string | null
  wayfair_category: string | null
  status: string
  evidence: string[]
  warnings: string[]
}
