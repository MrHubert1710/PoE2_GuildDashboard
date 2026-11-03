import { gotoHistory } from './workspace-helpers'
import { test, expect } from './fixtures'
import type { Page } from './fixtures'

test.use({ locale: 'en-US' })
const path = '/poe2guild/?chart_mode=quantity&lang=en'
const ready = (page: Page) => expect(page.getByTestId('transaction-results')).toBeVisible()
const panel = (page: Page) => page.getByTestId('refresh-panel')

test('active league without a configured source cannot fetch, and local verification runs on a real worker', async ({ page }) => {
  await gotoHistory(page, path)
  await ready(page)
  await expect(panel(page)).toContainText('The GGG history source is not yet available')
  await expect(panel(page)).toContainText('Worker online')
  await expect(page.getByTestId('sync-strip').getByRole('button', { name: 'Fetch history', exact: true })).toBeDisabled()
  await expect(panel(page)).toContainText('Last synchronization: none')
  await expect(panel(page)).not.toContainText('Last report generation: none')
  const url = new URL(page.url())
  const response = await page.request.post(`/poe2guild/api/leagues/${url.searchParams.get('league')}/refresh`, { data: { trigger: 'manual' } })
  expect((await response.json()).reason).toBe('source_unavailable')
  await page.getByRole('link', { name: 'Diagnostics', exact: true }).click()
  await panel(page).getByRole('button', { name: 'Verify local data' }).click()
  await expect(panel(page)).toContainText('Verified local records: 60', { timeout: 10000 })
  await expect(panel(page)).toContainText('Local verification: Job completed.')
  await expect(panel(page)).toContainText('Last synchronization: none')
  await expect(panel(page)).not.toContainText('Last report generation: none')
  expect(new URL(page.url()).searchParams.get('league')).toBe(url.searchParams.get('league'))
  await expect(page.locator('.history-transactions tbody tr')).toHaveCount(50)
})

test('status failure keeps the current data visible and later polling recovers', async ({ page }) => {
  let fail = true
  await page.route('**/refresh', route => route.request().method() === 'GET' && fail
    ? route.fulfill({ status: 503, json: { error: 'database_unavailable' } }) : route.continue())
  await gotoHistory(page, path)
  await ready(page)
  await expect(page.getByTestId('sync-strip').getByRole('alert')).toContainText('Unable to read refresh status')
  await expect(page.locator('.history-transactions tbody tr')).toHaveCount(50)
  fail = false
  await expect(page.getByTestId('sync-strip').getByRole('alert')).toHaveCount(0, { timeout: 10000 })
})

test('polling detects a new revision and refreshes rows while retaining URL and draft filters', async ({ page }) => {
  let changed = false
  await page.route('**/api/leagues', async route => {
    const response = await route.fetch()
    const payload = await response.json()
    if (changed) for (const league of payload.leagues) league.revision += '-new'
    await route.fulfill({ json: payload })
  })
  await page.route('**/transactions?*', async route => {
    const response = await route.fetch({ url: route.request().url().replace(/-new(?=&|$)/, '') })
    const payload = await response.json()
    if (changed) {
      payload.revision += '-new'
      payload.rows[0].item = 'Updated after publication'
    }
    await route.fulfill({ json: payload })
  })
  await page.route('**/refresh', async route => {
    const response = await route.fetch()
    const payload = await response.json()
    if (route.request().method() === 'GET' && changed) payload.revision += '-new'
    await route.fulfill({ json: payload })
  })
  await gotoHistory(page, path + '&page=2&page_size=25&sort=item&direction=asc&account=Synthetic%20Alice')
  await ready(page)
  await expect(panel(page)).toContainText('The GGG history source is not yet available')
  const url = page.url()
  await page.getByLabel('Player', { exact: true }).fill('Unsaved filter')
  changed = true
  await expect(page.locator('.history-transactions tbody')).toContainText('Updated after publication', { timeout: 12000 })
  expect(page.url()).toBe(url)
  await expect(page.getByLabel('Player', { exact: true })).toHaveValue('Unsaved filter')
  await expect(page.locator('.result-count')).toContainText('page 2')
})

test('waiting, source limits and offline worker are explicit and translate without reload', async ({ page }) => {
  await page.route('**/refresh', async route => {
    const response = await route.fetch()
    const payload = await response.json()
    if (route.request().method() === 'GET') {
      payload.worker = 'offline'
      payload.history.available = true
      payload.history.reason = null
      payload.history.automatic_retry_at = '2026-11-02T12:00:00Z'
      payload.history.job = { state: 'queued', attempts: 2, error_code: 'provider_limited', available_at: '2026-11-02T12:00:00Z' }
    }
    await route.fulfill({ json: payload })
  })
  await gotoHistory(page, path)
  await ready(page)
  await expect(panel(page)).toContainText('Worker offline')
  await expect(panel(page)).toContainText('Manual fetch also respects this waiting period')
  await expect(panel(page)).toContainText('Next automatic attempt available from')
  await page.getByRole('combobox', { name: 'Language', exact: true }).selectOption('pl')
  await expect(panel(page)).toContainText('Worker niedostępny')
  await expect(panel(page)).toContainText('Ręczny fetch także respektuje to oczekiwanie')
})

test('league switches discard stale status responses', async ({ page }) => {
  let unblock: () => void = () => {}
  const gate = new Promise<void>(resolve => { unblock = resolve })
  let delay = true
  await page.route('**/refresh', async route => {
    const response = await route.fetch()
    if (route.request().method() === 'GET' && delay) {
      delay = false
      await gate
    }
    await route.fulfill({ response }).catch(() => {})
  })
  await gotoHistory(page, path)
  await ready(page)
  await page.getByRole('combobox', { name: 'League', exact: true }).click()
  await page.getByRole('option', { name: 'Runes of Aldur', exact: false }).click()
  await expect(page.locator('.result-count')).toContainText('Results: 3')
  unblock()
  await expect(panel(page)).toContainText('The GGG history source is not yet available')
  await page.getByRole('link', { name: 'Diagnostics', exact: true }).click()
  await panel(page).getByRole('button', { name: 'Verify local data' }).click()
  await expect(panel(page)).toContainText('Verified local records: 3', { timeout: 10000 })
})

test('failed job submission stays visible even when status is available, and retry succeeds', async ({ page }) => {
  let fail = true
  await page.route('**/refresh', route => route.request().method() === 'POST' && route.request().postDataJSON().kind === 'local_verify' && fail
    ? route.fulfill({ status: 503, json: { error: 'database_unavailable' } }) : route.continue())
  await gotoHistory(page, path)
  await ready(page)
  await expect(panel(page)).toContainText('The GGG history source is not yet available')
  await page.getByRole('link', { name: 'Diagnostics', exact: true }).click()
  await panel(page).getByRole('button', { name: 'Verify local data' }).click()
  await expect(panel(page).getByRole('alert')).toContainText('Unable to submit the job')
  await expect(page.locator('.history-transactions tbody tr')).toHaveCount(50)
  fail = false
  await page.getByRole('link', { name: 'Diagnostics', exact: true }).click()
  await panel(page).getByRole('button', { name: 'Verify local data' }).click()
  await expect(panel(page).getByRole('alert')).toHaveCount(0)
  await expect(panel(page)).toContainText('Verified local records: 60', { timeout: 10000 })
})
