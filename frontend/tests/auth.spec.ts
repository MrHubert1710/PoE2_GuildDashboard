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

test('default password prompt opens on entry, can be skipped and changes the password through authenticated GUI',async({page})=>{
  // The shared fixture uses a custom admin password; simulate its initial warning flag.
  // Actual kalandra bootstrap, migration and authentication are covered by backend tests.
  let changed=false
  await page.route('**/api/auth/status',async route=>{
    const response=await route.fetch(),payload=await response.json()
    if(!changed)payload.default_password=true
    await route.fulfill({json:payload})
  })
  await page.route('**/api/auth/password',async route=>{
    const response=await route.fetch()
    if(response.ok())changed=true
    await route.fulfill({response})
  })
  const original='test-only-password-123',updated='new-browser-password-123'
  try {
    await page.goto(root+'?lang=en')
    const dialog=page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('still uses its default password')
    await page.setViewportSize({width:375,height:800})
    const bounds=(await dialog.boundingBox())!
    expect(bounds.x).toBeGreaterThanOrEqual(0)
    expect(bounds.x+bounds.width).toBeLessThanOrEqual(375)
    await page.setViewportSize({width:1280,height:900})
    await dialog.getByRole('button',{name:'Later (not recommended)',exact:true}).click()
    await expect(dialog).not.toBeVisible()
    await page.reload()
    await expect(dialog).toBeVisible()
    await dialog.getByLabel('Current password',{exact:true}).fill(original)
    await dialog.getByLabel('New password (at least 12 characters)',{exact:true}).fill(updated)
    await dialog.getByLabel('Repeat new password',{exact:true}).fill(updated)
    await dialog.getByRole('button',{name:'Set administrator password',exact:true}).click()
    await expect(dialog).toContainText('Password updated')
    await expect(page.getByTestId('admin-status')).toHaveText('Player')
    const status=await(await page.request.get(root+'api/auth/status')).json()
    expect(status.default_password).toBe(false)
    const response=await page.request.post(root+'api/auth/login',{data:{username:'admin',password:updated},headers:{'X-CSRF-Token':status.csrf_token}})
    expect(response.ok()).toBe(true)
    await page.reload()
    await expect(page.getByTestId('admin-status')).toHaveText('Admin')
    await expect(dialog).not.toBeVisible()
  } finally {
    if(changed){
      const status=await(await page.request.get(root+'api/auth/status')).json()
      const logged=await(await page.request.post(root+'api/auth/login',{data:{username:'admin',password:updated},headers:{'X-CSRF-Token':status.csrf_token}})).json()
      const response=await page.request.post(root+'api/auth/password',{data:{current_password:updated,password:original},headers:{'X-CSRF-Token':logged.csrf_token}})
      expect(response.ok()).toBe(true)
    }
  }
})
