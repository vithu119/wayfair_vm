import client from './client'
import type { TemplateEntry } from '../types'

export const uploadTemplates = async (files: File[]) => {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  const res = await client.post('/templates/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

export const listTemplates = async (): Promise<TemplateEntry[]> => {
  const res = await client.get('/templates')
  return res.data
}

export const getTemplate = async (templateId: string): Promise<TemplateEntry & { profile?: unknown }> => {
  const res = await client.get(`/templates/${templateId}`)
  return res.data
}

export const activateTemplate = async (templateId: string) => {
  const res = await client.post(`/templates/${templateId}/activate`)
  return res.data
}

export const deleteTemplate = async (templateId: string): Promise<void> => {
  await client.delete(`/templates/${templateId}`)
}

export const deleteAllTemplates = async (): Promise<void> => {
  await client.delete('/templates')
}
