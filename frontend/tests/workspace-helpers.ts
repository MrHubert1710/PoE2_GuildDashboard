import type { Page } from '@playwright/test'
export async function gotoHistory(page: Page, path: string) {
  const url = new URL(path, 'http://127.0.0.1:19003')
  if (url.searchParams.get('view') !== 'diagnostics' && !url.searchParams.has('section')) url.searchParams.set('section', 'history')
  await page.goto(url.toString())
}
export async function goSection(page: Page, name: string) {
  await page.getByRole('navigation', { name: /League views|Widoki ligi/ }).getByRole('link', { name, exact: true }).click()
}
