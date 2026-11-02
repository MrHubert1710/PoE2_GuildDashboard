import { test, expect } from './fixtures'
import { goSection } from './workspace-helpers'

test.use({ locale: 'en-US' })
const base='/poe2guild/?lang=en'
const nav=(page: import('@playwright/test').Page)=>page.getByRole('navigation',{name:'League views'})

test('default workspace presents summary and separates history, settings, archives and technical details',async({page})=>{
  await page.goto(base)
  await expect(nav(page).getByRole('link',{name:'Summary',exact:true})).toHaveAttribute('aria-current','page')
  await expect(page.locator('.overview-cards')).toContainText('60')
  await expect(page.getByTestId('transaction-results')).toBeHidden()
  await expect(page.getByTestId('quantity-settings')).toBeHidden()
  await expect(page.getByTestId('refresh-panel')).toBeHidden()
  await expect(page.getByRole('button',{name:'Verify local data'})).toHaveCount(0)
  await goSection(page,'History')
  await expect(page.getByTestId('transaction-results')).toBeVisible()
  await expect(page.getByTestId('quantity-panel')).toBeHidden()
  await goSection(page,'Settings')
  await expect(page.getByTestId('quantity-settings')).toBeVisible()
  await expect(page.locator('.workspace-filters')).toBeHidden()
  await goSection(page,'Archived reports')
  await expect(page.getByRole('link',{name:'currentday.html',exact:false})).toBeVisible()
  await page.getByRole('link',{name:'Diagnostics',exact:true}).click()
  await expect(page.getByTestId('refresh-panel')).toBeVisible()
  await expect(page.getByRole('button',{name:'Verify local data'})).toBeVisible()
})

test('filters, source page, details and unsaved drafts survive workspace navigation and Diagnostics',async({page})=>{
  await page.goto(base+'&section=history&page=2')
  await expect(page.locator('.result-count')).toContainText('page 2')
  const firstRow=page.locator('.history-transactions tbody tr').first()
  await firstRow.locator('summary').click()
  await page.getByLabel('Player',{exact:true}).fill('Unsaved player')
  await goSection(page,'Settings')
  await page.getByLabel('Display timezone',{exact:true}).fill('Europe/Paris')
  await goSection(page,'History')
  await expect(page.getByLabel('Player',{exact:true})).toHaveValue('Unsaved player')
  await expect(page.locator('.result-count')).toContainText('page 2')
  await expect(firstRow.locator('details')).toHaveAttribute('open','')
  await page.getByRole('link',{name:'Diagnostics',exact:true}).click()
  await expect(page.getByTestId('refresh-panel')).toBeVisible()
  await expect(page.locator('header').getByRole('combobox',{name:'League',exact:true})).toBeVisible()
  await page.getByRole('link',{name:'Workspace',exact:true}).click()
  await expect(page.locator('.result-count')).toContainText('page 2')
  await expect(page.getByLabel('Player',{exact:true})).toHaveValue('Unsaved player')
  await goSection(page,'Settings')
  await expect(page.getByLabel('Display timezone',{exact:true})).toHaveValue('Europe/Paris')
})

test('section, multi-stash filters and search modes survive reload/back/forward and language changes',async({page})=>{
  await page.goto(base+'&section=players&account=alice&account_regex=1&stash=Main&stash=Special')
  await expect(nav(page).getByRole('link',{name:'Players',exact:true})).toHaveAttribute('aria-current','page')
  await expect(page.getByTestId('quantity-panel').locator('.quantity-table')).toBeVisible()
  await goSection(page,'Stashes')
  await expect(page).toHaveURL(/section=stashes/)
  await page.goBack()
  await expect(nav(page).getByRole('link',{name:'Players',exact:true})).toHaveAttribute('aria-current','page')
  await page.goForward()
  await page.reload()
  await expect(nav(page).getByRole('link',{name:'Stashes',exact:true})).toHaveAttribute('aria-current','page')
  await expect(page.getByRole('button',{name:'Regex mode: Player',exact:true})).toHaveAttribute('aria-pressed','true')
  expect(new URL(page.url()).searchParams.getAll('stash')).toEqual(['Main','Special'])
  await page.getByRole('combobox',{name:'Language',exact:true}).selectOption('pl')
  await expect(page.getByRole('navigation',{name:'Widoki ligi'}).getByRole('link',{name:'Skrytki',exact:true})).toHaveAttribute('aria-current','page')
  await expect(page.getByRole('button',{name:'Tryb regex: Gracz',exact:true})).toHaveAttribute('aria-pressed','true')
})

test('section changes do not restart the automatic source request',async({page})=>{
  let automatic=0
  page.on('request',request=>{
    if(request.method()==='POST'&&request.url().endsWith('/refresh')) {
      const payload=request.postDataJSON()
      if(payload.kind==='history'&&payload.trigger==='automatic')automatic++
    }
  })
  await page.goto(base)
  await expect(page.getByTestId('quantity-panel')).toContainText('Generated:')
  for(const target of ['Players','Stashes','Stash state','History','Settings','Archived reports','Summary'])await goSection(page,target)
  expect(automatic).toBe(1)
})

test('legacy analysis links work and invalid section falls back to summary',async({page})=>{
  await page.goto(base+'&analysis=state')
  await expect(nav(page).getByRole('link',{name:'Stash state',exact:true})).toHaveAttribute('aria-current','page')
  await expect(page.getByTestId('quantity-panel').locator('.quantity-table')).toBeVisible()
  await page.goto(base+'&section=invalid')
  await expect(nav(page).getByRole('link',{name:'Summary',exact:true})).toHaveAttribute('aria-current','page')
})

test('mobile workspace has scrollable navigation and no document overflow in PL/EN',async({page})=>{
  await page.setViewportSize({width:390,height:844})
  await page.goto(base)
  await expect(page.getByTestId('time-series-chart')).toBeVisible()
  for(const target of ['Settings','Archived reports','History','Summary']) {
    await goSection(page,target)
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  }
  await page.getByRole('combobox',{name:'Language',exact:true}).selectOption('pl')
  await expect(page.getByRole('navigation',{name:'Widoki ligi'}).getByRole('link',{name:'Podsumowanie',exact:true})).toBeVisible()
  await page.screenshot({path:'test-results/phase-4b-mobile.png',fullPage:true})
})

test('league selection in Diagnostics keeps the destination and updates the same persistent workspace',async({page})=>{
  await page.goto(base)
  await expect(page.locator('.overview-cards')).toContainText('60')
  await page.getByRole('link',{name:'Diagnostics',exact:true}).click()
  await page.getByRole('combobox',{name:'League',exact:true}).click()
  await page.getByRole('option',{name:'Runes of Aldur',exact:false}).click()
  await expect(page).toHaveURL(/view=diagnostics/)
  await expect(page.locator('.league-context')).toContainText('Runes of Aldur')
  await page.getByRole('link',{name:'Workspace',exact:true}).click()
  await expect(nav(page).getByRole('link',{name:'Summary',exact:true})).toBeVisible()
  await expect(page.locator('.overview-cards article').first()).toContainText('3')
  await expect(page.locator('.history-transactions tbody tr')).toHaveCount(3)
})

test('refresh view retries the active report without rebuilding data or losing context',async({page})=>{
  let fail=true, rebuilds=0
  page.on('request',request=>{
    if(request.method()==='POST'&&request.url().endsWith('/refresh')&&request.postDataJSON().kind==='quantities')rebuilds++
  })
  await page.route('**/quantities?*',route=>fail?route.fulfill({status:503,json:{error:'database_unavailable'}}):route.continue())
  await page.goto(base+'&section=players&account=Alice')
  await expect(page.getByTestId('quantity-panel').getByRole('alert')).toContainText('database is unavailable')
  fail=false
  await page.getByRole('button',{name:'Refresh view',exact:true}).click()
  await expect(page.getByTestId('quantity-panel')).toContainText('Generated:')
  await expect(page.getByLabel('Player',{exact:true})).toHaveValue('Alice')
  await expect(nav(page).getByRole('link',{name:'Players',exact:true})).toHaveAttribute('aria-current','page')
  expect(rebuilds).toBe(0)
})
