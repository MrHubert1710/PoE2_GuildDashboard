import { onUnmounted } from 'vue'

class ApiError extends Error {}

export function useApiRequest(base: string, timeoutMs = 15000) {
  const controllers = new Set<AbortController>()
  let stopped = false
  async function request(path: string, options?: RequestInit) {
    const controller = new AbortController()
    controllers.add(controller)
    const timeout = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetch(base + path, { ...options, cache: 'no-store', signal: controller.signal })
      const payload = await response.json()
      if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new ApiError('report_unavailable')
      if (!response.ok) throw new ApiError(typeof payload.error === 'string' ? payload.error : 'report_unavailable')
      return payload
    } catch (error) {
      throw error instanceof ApiError ? error : new ApiError('report_unavailable')
    } finally { clearTimeout(timeout); controllers.delete(controller) }
  }
  onUnmounted(() => { stopped = true; controllers.forEach(controller => controller.abort()) })
  return { request, stopped: () => stopped }
}
