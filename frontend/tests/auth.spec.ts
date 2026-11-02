import { test, expect } from '@playwright/test'
const root='/poe2guild/'

test('Player has local settings but no diagnostics or server configuration, even via API',async({page,request})=>{
  await page.goto(root+'?lang=en&section=settings&view=diagnostics')
  await expect(page.getByTestId('admin-status')).toHaveText('Player')
  await expect(page.locator('.app-nav')).toHaveCount(0)
  await expect(page.locator('.diagnostics')).toHaveCount(0)
  await expect(page.getByTestId('client-settings')).toBeVisible()
  await expect(page.getByTestId('quantity-settings')).toHaveCount(0)
  for(const path of ['database-status','rework-readiness','leagues/anything/quantity-settings']) {
    expect((await request.get(root+'api/'+path)).status()).toBe(401)
  }
  expect((await request.post(root+'api/leagues/anything/refresh',{data:{kind:'local_verify'}})).status()).toBe(401)
})

test('login popup, Admin controls, reload persistence and logout remove protected content',async({page})=>{
  await page.goto(root+'?lang=en&section=settings')
  await page.getByTestId('admin-status').click()
  const dialog=page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByLabel('Username',{exact:true}).fill('test-admin')
  await dialog.getByLabel('Password',{exact:true}).fill('test-only-password-123')
  await dialog.getByRole('button',{name:'Log in',exact:true}).click()
  await expect(page.getByTestId('admin-status')).toHaveText('Admin')
  await expect(page.getByTestId('quantity-settings')).toBeVisible()
  await page.getByRole('link',{name:'Diagnostics',exact:true}).click()
  await expect(page.locator('.diagnostics')).toBeVisible()
  await page.reload()
  await expect(page.getByTestId('admin-status')).toHaveText('Admin')
  await expect(page.locator('.diagnostics')).toBeVisible()
  await page.getByTestId('admin-status').click()
  await dialog.getByRole('button',{name:'Log out',exact:true}).click()
  await expect(page.getByTestId('admin-status')).toHaveText('Player')
  await expect(page.locator('.diagnostics')).toHaveCount(0)
  await expect(page.getByTestId('quantity-settings')).toHaveCount(0)
  await expect(page.locator('.app-nav')).toHaveCount(0)
})
