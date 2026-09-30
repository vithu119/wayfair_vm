import client from './client'
import type { AsinValidation } from '../types'

export const validateAsins = async (asins: string[]): Promise<AsinValidation> => {
  const res = await client.post('/asins/validate', { asins })
  return res.data
}
