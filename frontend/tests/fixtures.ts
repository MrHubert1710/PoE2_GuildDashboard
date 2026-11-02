import { test as base, expect } from '@playwright/test'
export const test = base.extend({
  context: async ({ context }, use) => {
    const data = await (await context.request.get('/poe2guild/api/auth/status')).json()
    await context.request.post('/poe2guild/api/auth/login', { data: { username: 'test-admin', password: 'test-only-password-123' }, headers: { 'X-CSRF-Token': data.csrf_token } })
    await use(context)
  },
  request: async ({ context }, use) => {
    const status = await (await context.request.get('/poe2guild/api/auth/status')).json()
    const request = new Proxy(context.request, {get(target, prop) {
      const value = Reflect.get(target, prop)
      if (typeof value !== 'function') return value
      if (['put','post','patch','delete'].includes(String(prop))) return (url: string, options: any = {}) => value.call(target,url,{...options,headers:{...options.headers,'X-CSRF-Token':status.csrf_token}})
      return value.bind(target)
    }})
    await use(request)
  },
})
export { expect }

export type { Page, Locator, APIRequestContext } from '@playwright/test'
