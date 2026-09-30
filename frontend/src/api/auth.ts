import axios from 'axios'

const rawClient = axios.create({ baseURL: '/api', timeout: 10000 })

export interface TokenResponse {
  access_token: string
  token_type: string
  username: string
  is_admin: boolean
}

export async function login(username: string, password: string): Promise<TokenResponse> {
  const { data } = await rawClient.post<TokenResponse>('/auth/login', { username, password })
  return data
}

export async function register(username: string, password: string): Promise<TokenResponse> {
  const { data } = await rawClient.post<TokenResponse>('/auth/register', { username, password })
  return data
}
