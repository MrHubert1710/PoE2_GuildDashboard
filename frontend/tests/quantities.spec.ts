import { gotoHistory, goSection } from './workspace-helpers'
import { test, expect } from '@playwright/test'
import type { APIRequestContext } from '@playwright/test'

test.use({ locale: 'en-US' })
const path='/poe2guild/?lang=en'
async function restore(request: APIRequestContext) {
  const leagues=(await (await request.get('/poe2guild/api/leagues')).json()).leagues
  for(const league of leagues) {
    const url=`/poe2guild/api/leagues/${league.id}`
    const config=await (await request.get(url+'/quantity-settings')).json()
    await request.put(url+'/quantity-settings',{data:{settings:{target_stashes:null,stash_aliases:{},timezone:'UTC'},expected_hash:config.settings_hash,expected_guild_hash:config.guild_hash,scope:'guild'}})
    const current=await (await request.get(url+'/quantity-settings')).json()
    await request.put(url+'/quantity-settings',{data:{settings:current.settings,expected_hash:current.settings_hash,scope:'inherit'}})
    await request.post(url+'/refresh',{data:{kind:'quantities',trigger:'manual'}})
    await expect.poll(async()=> (await (await request.get(url+'/quantities')).json()).projection.state,{timeout:15000}).toBe('ready')
  }
}

test('Modified stays in source data and has a signed derived removal with explanation',async({page})=>{
  await gotoHistory(page, path)
  const row=page.locator('.history-transactions [data-event-id="12"]')
  await expect(row).toContainText('Modified')
  await expect(row.locator('.quantity-delta')).toHaveText('-5')
  await expect(row).toContainText('Removed')
  await row.getByText('Calculation basis',{exact:true}).click()
  await expect(row).toContainText('Before: 20 · after: 15')
  await expect(row).toContainText('Difference between known states')
  const panel=page.getByTestId('quantity-panel')
  await expect(panel).toContainText('Generated:')
  for(const view of ['Players','Stashes','Reconstructed state','Summary']) {
    await goSection(page, view === 'Reconstructed state' ? 'Stash state' : view)
    await expect(panel.locator('.quantity-table')).toBeVisible()
  }
})

test('history filters apply after replay and final state uses full history',async({page})=>{
  await page.goto(path)
  await expect(page.getByTestId('quantity-panel')).toContainText('Generated:')
  await page.getByLabel('Player',{exact:true}).fill('Synthetic Alice')
  await page.getByLabel('Item',{exact:true}).fill('Rites Token')
  await page.getByLabel('From day (UTC)').fill('2026-01-02')
  await page.getByRole('button',{name:'Apply filters'}).click()
  const panel=page.getByTestId('quantity-panel')
  await expect(panel.locator('.quantity-table')).toContainText('Rites Token')
  await goSection(page, 'Stash state')
  await expect(panel).toContainText('Player and date filters do not restrict this view')
  await expect(panel.locator('.quantity-table tbody tr').filter({hasText:'Rites Token'})).toContainText('63')
  await expect(page).toHaveURL(/analysis=state/)
  await page.reload()
  await expect(page.getByRole('navigation',{name:'League views'}).getByRole('link',{name:'Stash state',exact:true})).toHaveAttribute('aria-current','page')
})

test('league settings rebuild projections and change display timezone without altering source',async({page,request})=>{
  try {
    await page.goto(path)
    const panel=page.getByTestId('quantity-panel')
    await expect(panel).toContainText('Generated:')
    await goSection(page, 'Settings')
    await page.getByTestId('quantity-settings').getByLabel('Analyze all stashes',{exact:true}).uncheck()
    await page.getByTestId('quantity-settings').getByLabel('Special',{exact:true}).check()
    await page.getByTestId('quantity-settings').getByLabel('Display timezone',{exact:true}).fill('Europe/Warsaw')
    await page.getByTestId('quantity-settings').getByRole('button',{name:'Save settings and rebuild'}).click()
    await expect(page.locator('.history-transactions [data-event-id="12"]')).toContainText('Excluded',{timeout:15000})
    await goSection(page, 'History')
    await expect(page.getByRole('button',{name:'Date (Europe/Warsaw)',exact:false})).toBeVisible()
    await expect(panel.getByTestId('quantity-stats')).toContainText('excluded stashes: 59')
    await expect(page.locator('.history-transactions [data-event-id="12"]')).toContainText('Modified')
  } finally {await restore(request)}
})

test('guild aliases inherit into another league, while its item state starts independently',async({page,request})=>{
  try {
    await page.goto(path)
    const panel=page.getByTestId('quantity-panel')
    await expect(panel).toContainText('Generated:')
    await goSection(page, 'Settings')
    await page.getByTestId('quantity-settings').getByLabel('Alias for stash Main',{exact:true}).fill('Shared')
    await page.getByTestId('quantity-settings').getByLabel('Save settings for',{exact:true}).selectOption('guild')
    await page.getByTestId('quantity-settings').getByRole('button',{name:'Save settings and rebuild'}).click()
    await expect(panel).toContainText('Generated:',{timeout:15000})
    await page.getByRole('combobox',{name:'League',exact:true}).click()
    await page.getByRole('option',{name:'Runes of Aldur',exact:false}).click()
    await expect(panel).toContainText('Generated:',{timeout:15000})
    await goSection(page, 'Settings')
    await expect(page.getByTestId('quantity-settings').getByLabel('Alias for stash Main',{exact:true})).toHaveValue('Shared')
    await goSection(page, 'Stash state')
    await expect(panel.locator('.quantity-table')).toContainText('Shared')
    await expect(panel.locator('.quantity-table')).toContainText('Unknown')
    await expect(panel.locator('.quantity-table')).not.toContainText('63')
  } finally {await restore(request)}
})

test('analysis failure preserves source table and mobile translations remain within viewport',async({page})=>{
  await page.setViewportSize({width:360,height:800})
  await page.route('**/quantities?*',route=>route.fulfill({status:503,json:{error:'database_unavailable'}}))
  await page.goto(path)
  const panel=page.getByTestId('quantity-panel')
  await expect(panel.getByRole('alert')).toContainText('database is unavailable')
  await expect(page.locator('.history-transactions tbody tr')).toHaveCount(50)
  await page.getByRole('combobox',{name:'Language',exact:true}).selectOption('pl')
  await expect(panel.getByRole('alert')).toContainText('Baza danych jest niedostępna')
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
})
