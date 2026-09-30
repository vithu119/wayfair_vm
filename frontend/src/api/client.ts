import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 300000,
})

client.interceptors.request.use((config) => {
  try {
    const stored = localStorage.getItem('wayfair-auth')
    if (stored) {
      const { state } = JSON.parse(stored)
      if (state?.token) {
        config.headers.Authorization = `Bearer ${state.token}`
      }
    }
  } catch {
    // ignore parse errors
  }
  return config
})

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem('wayfair-auth')
      window.location.href = '/login'
      return Promise.reject(new Error('Session expired. Please log in again.'))
    }
    const message =
      error?.response?.data?.detail ||
      error?.response?.data?.message ||
      error?.message ||
      'An unexpected error occurred'
    return Promise.reject(new Error(typeof message === 'string' ? message : JSON.stringify(message)))
  }
)

export default client
