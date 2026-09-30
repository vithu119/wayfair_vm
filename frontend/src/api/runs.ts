import client from './client'
import type { Run, PreviewRow } from '../types'

export const createRun = async (): Promise<{ run_id: string }> => {
  const res = await client.post('/runs')
  return res.data
}

export const getRun = async (runId: string): Promise<Run> => {
  const res = await client.get(`/runs/${runId}`)
  return res.data
}

export const resolveRun = async (
  runId: string,
  body: { template_ids: string[]; source_ids: string[]; asins: string[]; template_profiles?: Record<string, unknown> }
) => {
  const res = await client.post(`/runs/${runId}/resolve`, body)
  return res.data
}

export const previewRun = async (runId: string): Promise<{ run_id: string; rows: PreviewRow[] }> => {
  const res = await client.get(`/runs/${runId}/preview`)
  return res.data
}

interface ProductHint { asin: string; sku?: string | null; product_name?: string | null }

export const sotFill = async (runId: string): Promise<{ filled: number; total: number }> => {
  const res = await client.post(`/runs/${runId}/sot-fill`)
  return res.data
}

export const patchValues = async (
  runId: string,
  edits: Record<string, string>,
  products?: ProductHint[],
) => {
  const res = await client.patch(`/runs/${runId}/values`, { edits, products: products ?? [] })
  return res.data
}

export const validateRun = async (runId: string) => {
  const res = await client.post(`/runs/${runId}/validate`)
  return res.data
}

export const getFindings = async (runId: string) => {
  const res = await client.get(`/runs/${runId}/findings`)
  return res.data
}

export const exportRun = async (runId: string) => {
  const res = await client.post(`/runs/${runId}/export`)
  return res.data
}

export const listDownloads = async (runId: string) => {
  const res = await client.get(`/runs/${runId}/downloads`)
  return res.data
}
