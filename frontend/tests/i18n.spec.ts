import { gotoHistory } from './workspace-helpers'
import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import { readFileSync, readdirSync } from 'node:fs'
import databaseFixture from '../../tests/fixtures/browser-database.json' with { type: 'json' }

test.use({ locale: 'en-US', timezoneId: 'Pacific/Auckland' })
const path = '/poe2guild/'
const ready = (page: Page) => expect(page.getByTestId('transaction-results')).toBeVisible()
const language = (page: Page) => page.locator('.language-picker select')
const settle = (page: Page) => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))

test('defaults to English and options come from locale file native names', async ({ page }) => {
  await gotoHistory(page, path)
  await ready(page)
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page).toHaveTitle('poe2guild — Guild history')
  await expect(page.getByRole('navigation',{name:'League views'}).getByRole('link',{name:'History',exact:true})).toBeVisible()
  const directory = new URL('../src/locales/', import.meta.url)
  const expected = readdirSync(directory).filter(name => name.endsWith('.json')).map(name => ({
    code: name.replace('.json', ''), nativeName: JSON.parse(readFileSync(new URL(name, directory), 'utf8')).nativeName,
  }))
  expect(await language(page).locator('option').evaluateAll(options => options.map(option => ({ code: (option as HTMLOptionElement).value, nativeName: option.textContent })))).toEqual(expected)
  await expect(page.getByRole('combobox', { name: 'Language', exact: true })).toHaveValue('en')
  await expect(page).toHaveURL(/lang=en/)
})

test('switch and back/forward keep league, filters, page, drafts and rows without any fetch', async ({ page }) => {
  await gotoHistory(page, path + '?lang=en&account=Synthetic%20Alice&page_size=25&page=2&sort=item&direction=asc&from=2026-01-01&to=2026-01-02')
  await ready(page)
  await expect(page.locator('.result-count')).toContainText('page 2')
  const before = new URL(page.url())
  const rows = await page.locator('.history-transactions tbody').textContent()
  const row = await page.locator('.history-transactions tbody tr').first().elementHandle()
  await page.getByLabel('Player', { exact: true }).fill('unsubmitted draft')
  const requests: string[] = []
  // The regular status poll runs independently of language navigation.
  page.on('request', request => { if (request.url().includes('/api/') && !(request.method() === 'GET' && request.url().endsWith('/refresh'))) requests.push(request.url()) })
  await language(page).selectOption('pl')
  await expect(page.getByRole('navigation',{name:'Widoki ligi'}).getByRole('link',{name:'Historia',exact:true})).toBeVisible()
  await expect(page.getByLabel('Gracz', { exact: true })).toHaveValue('unsubmitted draft')
  await expect(page.getByRole('region', { name: 'Tabela transakcji — przewijanie poziome' })).toBeVisible()
  for (const [key, value] of before.searchParams) if (key !== 'lang') expect(new URL(page.url()).searchParams.get(key)).toBe(value)
  expect(await page.locator('.history-transactions tbody').textContent()).toContain('Synthetic Alice')
  expect(await row!.evaluate(element => element.isConnected)).toBe(true)
  await page.goBack()
  await expect(language(page)).toHaveValue('en')
  expect(await page.locator('.history-transactions tbody').textContent()).toBe(rows)
  await page.goForward()
  await expect(language(page)).toHaveValue('pl')
  await settle(page)
  expect(requests).toEqual([])
  await page.reload()
  await ready(page)
  await expect(language(page)).toHaveValue('pl')
  await expect(page.locator('.result-count')).toContainText('strona 2')
})

test('language persists between views, links, reload and URL overrides saved preference', async ({ page }) => {
  await gotoHistory(page, path + '?lang=pl')
  await ready(page)
  await page.getByRole('link', { name: 'Diagnostyka', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Archiwa lig' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Panel gildii', exact: true })).toHaveAttribute('href', /lang=pl/)
  await page.reload()
  await expect(language(page)).toHaveValue('pl')
  await gotoHistory(page, path)
  await ready(page)
  await expect(language(page)).toHaveValue('pl')
  await gotoHistory(page, path + '?lang=en')
  await ready(page)
  await expect(language(page)).toHaveValue('en')
})

test('unsupported or removed locale falls back through saved, browser and English', async ({ browser }) => {
  for (const [browserLocale, saved, expected] of [
    ['pl-PL', 'en', 'en'], ['pl-PL', 'removed-locale', 'pl'], ['fr-FR', 'removed-locale', 'en'],
  ]) {
    const context = await browser.newContext({ locale: browserLocale })
    try {
      await context.addInitScript(value => localStorage.setItem('poe2guild.language', value), saved!)
      const page = await context.newPage()
      await gotoHistory(page, 'http://127.0.0.1:19003' + path + '?lang=removed-locale')
      await ready(page)
      await expect(language(page)).toHaveValue(expected!)
      expect(new URL(page.url()).searchParams.get('lang')).toBe(expected)
    } finally { await context.close() }
  }
})

test('denied browser storage still allows URL-based switching and reload', async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(window, 'localStorage', { get() { throw new Error('Storage denied') } }) })
  await gotoHistory(page, path)
  await ready(page)
  await language(page).selectOption('pl')
  await page.reload()
  await ready(page)
  await expect(language(page)).toHaveValue('pl')
})

test('existing errors translate immediately without retrying the API', async ({ page }) => {
  await page.route('**/transactions?*', route => route.fulfill({ status: 409, json: { error: 'revision_changed' } }))
  await gotoHistory(page, path)
  await expect(page.getByRole('alert')).toContainText('League data has changed')
  const requests: string[] = []
  // The regular status poll runs independently of language navigation.
  page.on('request', request => { if (request.url().includes('/api/') && !(request.method() === 'GET' && request.url().endsWith('/refresh'))) requests.push(request.url()) })
  await language(page).selectOption('pl')
  await expect(page.getByRole('alert')).toContainText('Dane ligi zmieniły się')
  await settle(page)
  expect(requests).toEqual([])
})

test('diagnostics keeps expanded evidence, formats numbers and translates provider metadata', async ({ page }) => {
  await page.route('**/api/database-status', route => route.fulfill({ json: databaseFixture }))
  await gotoHistory(page, path + '?view=diagnostics&lang=en')
  await expect(page.getByTestId('database-summary')).toContainText('104,534 transactions in SQLite')
  const evidence = page.locator('[data-league]').first().locator('details')
  await evidence.locator('summary').click()
  const requests: string[] = []
  // The regular status poll runs independently of language navigation.
  page.on('request', request => { if (request.url().includes('/api/') && !(request.method() === 'GET' && request.url().endsWith('/refresh'))) requests.push(request.url()) })
  await language(page).selectOption('pl')
  await expect(evidence).toHaveAttribute('open', '')
  await expect(page.getByTestId('database-summary')).toContainText('104\u00a0534 transakcje w SQLite')
  await expect(page.getByRole('heading', { name: 'Historia skrytki gildii PoE2' })).toBeVisible()
  await expect(page.getByText('Brak publicznego kontraktu')).toHaveCount(2)
  await settle(page)
  expect(requests).toEqual([])
})

test('dates use the language with UTC independent of browser timezone', async ({ page }) => {
  await gotoHistory(page, path + '?lang=en')
  await ready(page)
  const expected = await page.evaluate(async () => {
    const params = new URLSearchParams(location.search)
    const payload = await (await fetch(`api/leagues/${params.get('league')}/transactions?sort=date&direction=desc`)).json()
    return new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(payload.rows[0].occurred_at))
  })
  await expect(page.locator('.date-cell').first()).toHaveText(expected)
  await language(page).selectOption('pl')
  await expect(page.locator('.date-cell').first()).not.toHaveText(expected)
  await expect(page.getByRole('button', { name: 'Data (UTC)', exact: false })).toBeVisible()
})

test('mobile header, long labels, statuses and filters stay inside viewport in both languages', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 })
  await gotoHistory(page, path)
  await ready(page)
  for (const code of ['pl', 'en']) {
    await language(page).selectOption(code)
    await expect(page.locator('header .league-picker')).toBeVisible()
    await page.locator('.league-picker > button').click()
    await expect(page.locator('.league-options .league-status')).toHaveText(code === 'pl' ? ['Archiwalna', 'Archiwalna'] : ['Archived', 'Archived'])
    await page.locator('.league-picker > button').press('Escape')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: `test-results/phase-2a-mobile-${code}.png`, fullPage: true })
  }
})
