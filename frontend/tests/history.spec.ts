import { gotoHistory, goSection } from './workspace-helpers'
import { test, expect } from './fixtures'

test.use({ locale: 'pl-PL' })

const path = '/poe2guild/?chart_mode=quantity&lang=pl'
const results = (page: import('@playwright/test').Page) => page.getByTestId('transaction-results')

test('switches leagues and limits each server page', async ({ page }) => {
  await gotoHistory(page, path)
  await expect(results(page)).toContainText('Wyniki: 60')
  await expect(page.locator('.history-transactions tbody tr')).toHaveCount(50)
  await page.getByRole('button', { name: 'Następna' }).click()
  await expect(page.locator('.history-transactions tbody tr')).toHaveCount(10)
  await expect(page).toHaveURL(/page=2/)
  await page.getByRole('combobox', { name: 'Liga', exact: true }).click()
  await page.getByRole('option', { name: 'Runes of Aldur', exact: false }).click()
  await expect(results(page)).toContainText('Wyniki: 3')
  await expect(page.locator('.history-transactions tbody')).toContainText('Aldur Token')
  await expect(page.locator('.history-transactions tbody')).not.toContainText('Rites Token')
  await expect(page.locator('.history-transactions tbody tr')).toHaveCount(3)
})

test('filters, sorts and restores state through reload and browser history', async ({ page }) => {
  await gotoHistory(page, path)
  await expect(results(page)).toBeVisible()
  await page.getByLabel('Gracz', { exact: true }).fill('ŻÓŁW')
  await page.getByRole('button', { name: 'Zastosuj filtry' }).click()
  await expect(results(page)).toContainText('Wyniki: 30')
  await page.getByRole('button', { name: 'Data (UTC)' }).click()
  await expect(page.locator('.history-transactions tbody tr').first()).toHaveAttribute('data-event-id', '1')
  await expect(page).toHaveURL(/direction=asc/)
  await page.reload()
  await expect(page.getByLabel('Gracz', { exact: true })).toHaveValue('ŻÓŁW')
  await expect(results(page)).toContainText('Wyniki: 30')
  await page.getByLabel('Przedmiot', { exact: true }).fill('%_')
  await page.getByRole('button', { name: 'Zastosuj filtry' }).click()
  await expect(results(page)).toContainText('Wyniki: 1')
  await page.goBack()
  await expect(page.getByLabel('Przedmiot', { exact: true })).toHaveValue('')
  await expect(results(page)).toContainText('Wyniki: 30')
  await page.goForward()
  await expect(page.getByLabel('Przedmiot', { exact: true })).toHaveValue('%_')
  await expect(results(page)).toContainText('Wyniki: 1')
})

test('combines stash and inclusive day filters and shows no matches', async ({ page }) => {
  await gotoHistory(page, path)
  await expect(results(page)).toBeVisible()
  await page.getByRole('group', { name: 'Skrytki', exact: true }).getByRole('button', { name: 'Skrytki', exact: true }).click()
  await page.getByRole('group', { name: 'Skrytki', exact: true }).getByRole('checkbox', { name: 'Special', exact: true }).check()
  await page.getByLabel('Od dnia (UTC)').fill('2026-01-01')
  await page.getByLabel('Do dnia (UTC)').fill('2026-01-01')
  await page.getByRole('button', { name: 'Zastosuj filtry' }).click()
  await expect(results(page)).toContainText('Wyniki: 1')
  await page.getByLabel('Przedmiot', { exact: true }).fill('does-not-exist')
  await page.getByRole('button', { name: 'Zastosuj filtry' }).click()
  await expect(page.getByText('Brak transakcji dla wybranych filtrów.')).toBeVisible()
  await page.getByRole('button', { name: 'Wyczyść filtry' }).click()
  await expect(results(page)).toContainText('Wyniki: 60')
})

test('a delayed old league response cannot overwrite the current league', async ({ page }) => {
  await gotoHistory(page, path)
  await expect(results(page)).toBeVisible()
  const oldId = new URL(page.url()).searchParams.get('league')!
  let release!: () => void
  const blocked = new Promise<void>(resolve => { release = resolve })
  let captured!: () => void
  const entered = new Promise<void>(resolve => { captured = resolve })
  await page.route(`**/leagues/${oldId}/transactions?**`, async route => {
    const response = await route.fetch()
    captured()
    await blocked
    await route.fulfill({ response }).catch(() => {})
  })
  await page.getByRole('button', { name: 'Następna' }).click()
  await entered
  await page.getByRole('combobox', { name: 'Liga', exact: true }).click()
  await page.getByRole('option', { name: 'Runes of Aldur', exact: false }).click()
  await expect(results(page)).toContainText('Wyniki: 3')
  release()
  await expect(page.locator('.history-transactions tbody')).toContainText('Aldur Token')
  await expect(page.locator('.history-transactions tbody')).not.toContainText('Rites Token')
})

test('API failure, revision conflict and retry preserve selected filters', async ({ page }) => {
  await gotoHistory(page, path)
  await expect(results(page)).toBeVisible()
  await page.route('**/transactions?**', route => route.fulfill({ status: 409, json: { error: 'revision_changed' } }))
  await page.getByLabel('Gracz', { exact: true }).fill('Alice')
  await page.getByRole('button', { name: 'Zastosuj filtry' }).click()
  await expect(page.getByRole('alert')).toContainText('Dane ligi zmieniły się')
  await page.unroute('**/transactions?**')
  await page.getByRole('button', { name: 'Odśwież widok' }).click()
  await expect(page.getByLabel('Gracz', { exact: true })).toHaveValue('Alice')
  await expect(results(page)).toContainText('Wyniki: 30')
})

test('list failure can be retried and an empty list is distinct from failure', async ({ page }) => {
  await page.route('**/api/leagues', route => route.fulfill({ status: 503, json: {} }))
  await gotoHistory(page, path)
  await expect(page.getByRole('alert')).toContainText('listy lig')
  await page.unroute('**/api/leagues')
  await page.getByRole('button', { name: 'Odśwież widok' }).click()
  await expect(results(page)).toBeVisible()
  await page.route('**/api/leagues', route => route.fulfill({ json: { leagues: [] } }))
  await page.getByRole('button', { name: 'Odśwież widok' }).click()
  await expect(page.getByText('Brak lig w bazie.', { exact: false })).toBeVisible()
})

test('unknown URL league is explicit and out-of-range pages are canonicalized', async ({ page }) => {
  await gotoHistory(page, path + '&league=missing')
  await expect(page.getByRole('alert')).toContainText('Liga wskazana w adresie')
  await page.getByRole('button', { name: 'Wybierz pierwszą ligę' }).click()
  await expect(results(page)).toBeVisible()
  const id = new URL(page.url()).searchParams.get('league')!
  await gotoHistory(page, path + `&league=${id}&page=999`)
  await expect(results(page)).toContainText('strona 2 z 2')
  await expect(page).toHaveURL(/page=2/)
})

test('HTML text in source item names is escaped', async ({ page }) => {
  await gotoHistory(page, path)
  await expect(results(page)).toBeVisible()
  await page.getByLabel('Przedmiot', { exact: true }).fill('<img')
  await page.getByRole('button', { name: 'Zastosuj filtry' }).click()
  await expect(page.locator('.history-transactions tbody')).toContainText('<img src=x')
  await expect(page.locator('.history-transactions tbody img')).toHaveCount(0)

})

test('mobile page stays within viewport and diagnostics remain accessible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await gotoHistory(page, path)
  await expect(results(page)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/phase-2-mobile.png', fullPage: true })
  await page.getByRole('link', { name: 'Diagnostyka', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Baza danych', exact: true })).toBeVisible()
  await page.goBack()
  await expect(page.getByRole('navigation',{name:'Widoki ligi'}).getByRole('link',{name:'Historia',exact:true})).toBeVisible()
})

test('compact league picker shows per-option status, supports keyboard and hides event IDs', async ({ page }) => {
  await page.route('**/api/leagues', async route => {
    const response = await route.fetch()
    const payload = await response.json()
    payload.leagues[0].lifecycle = 'ended'
    payload.leagues[1].lifecycle = 'active'
    await route.fulfill({ json: payload })
  })
  await gotoHistory(page, path)
  await expect(results(page)).toBeVisible()
  await expect(page.locator('.history-transactions').getByRole('columnheader', { name: 'ID zdarzenia' })).toHaveCount(0)
  await expect(page.locator('.history-transactions thead th')).toHaveCount(8)
  const picker = page.getByRole('combobox', { name: 'Liga', exact: true })
  await expect(page.locator('header').getByRole('combobox', { name: 'Liga', exact: true })).toBeVisible()
  await picker.focus()
  await picker.press('ArrowDown')
  await expect(picker).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('option', { name: 'Forbidden Rites', exact: false })).toContainText('Archiwalna')
  await expect(page.getByRole('option', { name: 'Runes of Aldur', exact: false })).toContainText('Aktywna')
  await picker.press('End')
  await picker.press('Enter')
  await expect(results(page)).toContainText('Wyniki: 3')
  await expect(picker).toContainText('Aktywna')
  await picker.press('Enter')
  await picker.press('Escape')
  await expect(picker).toHaveAttribute('aria-expanded', 'false')
  await picker.click()
  await page.locator('footer').click()
  await expect(picker).toHaveAttribute('aria-expanded', 'false')
})
