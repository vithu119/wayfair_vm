import client from './client'

export interface AdminUser {
  user_id: string
  username: string
  is_admin: boolean
  created_at: string | null
  run_count: number
}

export async function getAdminUsers(): Promise<AdminUser[]> {
  const { data } = await client.get<AdminUser[]>('/admin/users')
  return data
}
