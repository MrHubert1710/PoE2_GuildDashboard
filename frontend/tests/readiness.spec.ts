import { test, expect } from './fixtures'

test.use({ locale: 'pl-PL' })
import databaseFixture from '../../tests/fixtures/browser-database.json' with { type: 'json' }

test.beforeEach(async ({ page }) => {
  await page.route('**/api/database-status', route => route.fulfill({ json: databaseFixture }))
})

test('renders both archives, expands evidence and refreshes without navigation', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/poe2guild/?lang=pl&view=diagnostics')
  await expect(page.getByRole('heading', { name: 'Archiwa lig' })).toBeVisible()
  const aldur = page.locator('[data-league="Runes of Aldur"]')
  const rites = page.locator('[data-league="Forbidden Rites"]')
  await expect(aldur).toContainText(/89\s*190/)
  await expect(rites).toContainText(/15\s*344/)
  await expect(page.locator('.diagnostics [role="status"]').first()).toContainText(/104\s*534/)
  await aldur.getByText('Sumy kontrolne i zachowane pliki').click()
  await expect(aldur.getByText('currentday.html', { exact: false })).toBeVisible()
  await expect(aldur.getByText('lastday.html', { exact: false })).toBeVisible()
  const navigation: string[] = []
  page.on('framenavigated', frame => navigation.push(frame.url()))
  await page.getByRole('button', { name: 'Odśwież podgląd' }).click()
  await expect(page.getByRole('button', { name: 'Odśwież podgląd' })).toBeEnabled()
  await expect(aldur.locator('details')).toHaveAttribute('open', '')
  expect(navigation).toEqual([])
  expect(errors).toEqual([])
})

test('shows API failure and supports retry', async ({ page }) => {
  let fail = true
  await page.route('**/api/rework-readiness', route => fail
    ? route.fulfill({ status: 503, json: { error: 'Reference unavailable' } })
    : route.continue())
  await page.goto('/poe2guild/?lang=pl&view=diagnostics')
  await expect(page.getByRole('alert')).toContainText('spróbuj ponownie')
  fail = false
  await page.getByRole('button', { name: 'Odśwież podgląd' }).click()
  await expect(page.getByRole('heading', { name: 'Archiwa lig' })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('retains last snapshot on a later API failure', async ({ page }) => {
  await page.goto('/poe2guild/?lang=pl&view=diagnostics')
  await expect(page.getByRole('heading', { name: 'Archiwa lig' })).toBeVisible()
  await page.route('**/api/rework-readiness', route => route.fulfill({ status: 503, json: {} }))
  await page.getByRole('button', { name: 'Odśwież podgląd' }).click()
  await expect(page.getByRole('alert')).toContainText('ostatni odczytany wynik')
  await expect(page.locator('[data-league]')).toHaveCount(2)
})

test('mobile layout has no horizontal overflow and reports integration limits', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/poe2guild/?lang=pl&view=diagnostics')
  await expect(page.getByRole('heading', { name: 'Archiwa lig' })).toBeVisible()
  await page.locator('[data-league]').first().getByText('Sumy kontrolne i zachowane pliki').click()
  await expect(page.getByText('czas cen niepotwierdzony').first()).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.getByRole('heading', { name: 'Historia skrytki gildii PoE2' })).toBeVisible()
  await expect(page.getByText('Brak publicznego kontraktu')).toHaveCount(2)
  await page.screenshot({ path: 'test-results/phase-1-mobile.png', fullPage: true })
})

test('shows database counts, integrity and duplicate import result', async ({ page }) => {
  await page.goto('/poe2guild/?lang=pl&view=diagnostics')
  const database = page.getByTestId('database-summary')
  await expect(database).toContainText(/104\s*534 transakcje w SQLite/)
  await expect(database.getByText('Integralność OK')).toBeVisible()
  await expect(page.getByText('Zgodna z audytem')).toHaveCount(2)
  await database.getByText('Ostatni import', { exact: false }).click()
  await expect(database).toContainText('Pominięte duplikaty')
  await expect(database).toContainText(/104\s*534/)
})

test('database failure leaves independent reference archives available', async ({ page }) => {
  await page.route('**/api/database-status', route => route.fulfill({ status: 503, json: { state: 'unavailable' } }))
  await page.goto('/poe2guild/?lang=pl&view=diagnostics')
  await expect(page.getByTestId('database-error')).toContainText('Baza jest niedostępna')
  await expect(page.locator('[data-league]')).toHaveCount(2)
  await expect(page.getByTestId('database-summary')).toHaveCount(0)
})

test('later database failure preserves the last visible database result', async ({ page }) => {
  await page.goto('/poe2guild/?lang=pl&view=diagnostics')
  await expect(page.getByTestId('database-summary')).toBeVisible()
  await page.route('**/api/database-status', route => route.fulfill({ status: 503, json: {} }))
  await page.getByRole('button', { name: 'Odśwież podgląd' }).click()
  await expect(page.getByTestId('database-error')).toContainText('ostatni odczytany wynik')
  await expect(page.getByTestId('database-summary')).toBeVisible()
})
