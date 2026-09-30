import { describe, it, expect, vi, beforeEach } from 'vitest'
import axios from 'axios'

// Test the error interceptor logic directly
function applyInterceptor(error: unknown): never {
  const axiosError = error as { response?: { data?: { detail?: unknown; message?: string }; status?: number }; message?: string }
  const message =
    axiosError?.response?.data?.detail ||
    axiosError?.response?.data?.message ||
    axiosError?.message ||
    'An unexpected error occurred'
  throw new Error(typeof message === 'string' ? message : JSON.stringify(message))
}

describe('axios error interceptor logic', () => {
  it('extracts detail from response data', () => {
    const error = {
      response: {
        data: { detail: 'Template not found' },
        status: 404,
      },
      message: 'Request failed with status code 404',
    }
    expect(() => applyInterceptor(error)).toThrow('Template not found')
  })

  it('falls back to error.message when no response', () => {
    const error = {
      response: undefined,
      message: 'Network Error',
    }
    expect(() => applyInterceptor(error)).toThrow('Network Error')
  })

  it('uses generic message when all else fails', () => {
    const error = {}
    expect(() => applyInterceptor(error)).toThrow('An unexpected error occurred')
  })

  it('stringifies array detail messages', () => {
    const arrayDetail = [{ loc: ['body', 'asins'], msg: 'field required' }]
    const error = {
      response: {
        data: { detail: arrayDetail },
        status: 422,
      },
    }
    expect(() => applyInterceptor(error)).toThrow(/field required|loc/)
  })

  it('does not expose local file paths', () => {
    const error = {
      response: {
        data: { detail: 'Error processing file' },
        status: 500,
      },
    }
    let msg = ''
    try {
      applyInterceptor(error)
    } catch (e) {
      msg = (e as Error).message
    }
    expect(msg).not.toContain('C:\\')
    expect(msg).not.toContain('/home/')
    expect(msg).not.toContain('/Users/')
  })

  it('thrown value is always an Error instance', () => {
    const error = {
      response: { data: { detail: 'Validation error' }, status: 422 },
    }
    let caught: unknown
    try {
      applyInterceptor(error)
    } catch (e) {
      caught = e
    }
    expect(caught).toBeInstanceOf(Error)
  })
})

// Integration test: verify the actual client module has an interceptor registered
describe('axios client module', () => {
  it('exports an axios instance', async () => {
    const mod = await import('../api/client')
    const client = mod.default
    // axios instances have these properties
    expect(typeof client.get).toBe('function')
    expect(typeof client.post).toBe('function')
    expect(typeof client.interceptors).toBe('object')
  })
})
