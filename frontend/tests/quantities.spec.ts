import { gotoHistory, goSection, zoomTime } from './workspace-helpers'
import { test, expect } from './fixtures'
import type { APIRequestContext } from './fixtures'

test.use({ locale: 'en-US' })
const path='/poe2guild/?chart_mode=quantity&lang=en'
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
    await goSection(page, 'System settings')
    await page.getByTestId('quantity-settings').getByLabel('Analyze all stashes',{exact:true}).uncheck()
    await page.getByTestId('quantity-settings').getByRole('checkbox',{name:'Include stash Special',exact:true}).check()
    await goSection(page, 'Settings')
    await page.getByTestId('client-settings').getByLabel('Display timezone',{exact:true}).fill('Europe/Warsaw')
    await page.getByTestId('client-settings').getByRole('button',{name:'Save preferences',exact:true}).click()
    await goSection(page, 'System settings')
    await page.getByTestId('quantity-settings').getByRole('button',{name:'Save settings and rebuild'}).click()
    await expect(page.locator('.history-transactions [data-event-id="12"]')).toHaveCount(0)
    await goSection(page, 'History')
    await expect(page.getByRole('button',{name:'Date (Europe/Warsaw)',exact:false})).toBeVisible()
    await expect(panel.getByTestId('quantity-stats')).toContainText('Events: 1 ·',{timeout:15000})
    await expect(page.locator('.result-count')).toContainText('Results: 1')
  } finally {await restore(request)}
})

test('guild aliases inherit into another league, while its item state starts independently',async({page,request})=>{
  try {
    await page.goto(path)
    const panel=page.getByTestId('quantity-panel')
    await expect(panel).toContainText('Generated:')
    await goSection(page, 'System settings')
    await page.getByTestId('quantity-settings').getByLabel('Alias for stash Main',{exact:true}).fill('Shared')
    await page.getByTestId('quantity-settings').getByLabel('Save settings for',{exact:true}).selectOption('guild')
    await page.getByTestId('quantity-settings').getByRole('button',{name:'Save settings and rebuild'}).click()
    await expect(panel).toContainText('Generated:',{timeout:15000})
    await page.getByRole('combobox',{name:'League',exact:true}).click()
    await page.getByRole('option',{name:'Runes of Aldur',exact:false}).click()
    await expect(panel).toContainText('Generated:',{timeout:15000})
    await goSection(page, 'System settings')
    await expect(page.getByTestId('quantity-settings').getByLabel('Alias for stash Main',{exact:true})).toHaveValue('Shared')
    await goSection(page, 'Stash state')
    await expect(panel.locator('.quantity-table')).toContainText('Shared')
    await expect(panel.locator('.quantity-table')).not.toContainText('Unknown')
    await expect(panel.locator('.quantity-table tbody tr').filter({hasText:'Aldur Token'}).locator('td').nth(3)).toHaveText('2')
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


test('first Added starts from zero and the first Modified uses the accumulated stack',async({page})=>{
  await gotoHistory(page,path+'&direction=asc')
  const first=page.locator('.history-transactions [data-event-id="1"]')
  await first.getByText('Calculation basis',{exact:true}).click()
  await expect(first).toContainText('Before: 0 · after: 1')
  const modified=page.locator('.history-transactions [data-event-id="11"]')
  await expect(modified.locator('.quantity-delta')).toHaveText('+14')
  await modified.getByText('Calculation basis',{exact:true}).click()
  await expect(modified).toContainText('Before: 6 · after: 20')
})


test('stash inclusion sits beside renaming, survives renaming and preserves source history',async({page,request})=>{
  try {
    await page.goto(path+'&section=configuration')
    const settings=page.getByTestId('quantity-settings')
    const main=settings.getByRole('checkbox',{name:'Include stash Main',exact:true})
    const special=settings.getByRole('checkbox',{name:'Include stash Special',exact:true})
    await expect(main).toBeChecked()
    await expect(special).toBeChecked()
    await main.uncheck()
    await expect(special).toBeChecked()
    await settings.getByLabel('Alias for stash Main',{exact:true}).fill('Ignored stash')
    await expect(main).not.toBeChecked()
    await settings.getByRole('button',{name:'Save settings and rebuild'}).click()
    await expect(main).not.toBeChecked()
    await goSection(page,'History')
    await expect(page.locator('.history-transactions [data-event-id="12"]')).toHaveCount(0)
    await expect(page.locator('.result-count')).toContainText('Results: 1')
    await goSection(page,'System settings')
    await main.check()
    await settings.getByLabel('Alias for stash Main',{exact:true}).fill('Renamed stash')
    await expect(main).toBeChecked()
    await settings.getByRole('button',{name:'Save settings and rebuild'}).click()
    await page.reload()
    await expect(main).toBeChecked()
    await expect(settings.getByLabel('Alias for stash Main',{exact:true})).toHaveValue('Renamed stash')
    await goSection(page,'Stash state')
    await expect(page.getByTestId('quantity-panel').locator('.quantity-table')).toContainText('Renamed stash',{timeout:15000})
    await goSection(page,'System settings')
    await page.setViewportSize({width:390,height:844})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  } finally {await restore(request)}
})


test('timezone accepts fixed UTC offsets and abbreviations and formats dates across day boundaries',async({page,request})=>{
  try {
    await page.goto(path+'&section=settings')
    const settings=page.getByTestId('client-settings')
    for(const [input,canonical,time] of [['UTC+13','UTC+13:00','Jan 3, 2026, 1:00 AM'],['PST','UTC-08:00','Jan 2, 2026, 4:00 AM'],['UTC+5.5','UTC+05:30','Jan 2, 2026, 5:30 PM']]) {
      await settings.getByLabel('Display timezone',{exact:true}).fill(input)
      await settings.getByRole('button',{name:'Save preferences'}).click()
      await expect(settings.getByLabel('Display timezone',{exact:true})).toHaveValue(canonical)
      await goSection(page,'History')
      await expect(page.getByRole('button',{name:`Date (${canonical})`,exact:false})).toBeVisible()
      await expect(page.locator('.history-transactions tbody tr').first()).toContainText(time)
      await goSection(page,'Settings')
    }
    await settings.getByLabel('Display timezone',{exact:true}).fill('UTC+25')
    await settings.getByRole('button',{name:'Save preferences'}).click()
    await expect(settings.getByRole('alert')).toContainText('Invalid timezone')
    await page.reload()
    await expect(settings.getByLabel('Display timezone',{exact:true})).toHaveValue('UTC+05:30')
    await expect(page.locator('#client-timezones option[value="PST"]')).toHaveText('PST (UTC-08:00)')
  } finally {await restore(request)}
})


test('disabling a selected stash clears its filter, hides it everywhere and reports rebuild progress',async({page,request})=>{
  let hold=false
  await page.route('**/quantities?*',async route=>{
    const response=await route.fetch()
    if(!hold) return route.fulfill({response})
    const data=await response.json()
    await route.fulfill({response,json:{...data,projection:{...data.projection,state:'stale',id:null},rows:[],stats:null}})
  })
  try {
    await page.goto(path+'&section=history&stash=Main')
    await expect(page.locator('.result-count')).toContainText('Results: 59')
    await goSection(page,'System settings')
    await page.getByRole('checkbox',{name:'Include stash Main',exact:true}).uncheck()
    hold=true
    await page.getByRole('button',{name:'Save settings and rebuild'}).click()
    await expect(page.getByTestId('projection-status')).toContainText('please wait')
    await goSection(page,'History')
    await expect(page.locator('.result-count')).toContainText('Results: 1')
    expect(new URL(page.url()).searchParams.getAll('stash')).toEqual([])
    await page.getByRole('button',{name:'Stashes',exact:true}).click()
    await expect(page.locator('.stash-filter-options').getByRole('checkbox',{name:'Main',exact:true})).toHaveCount(0)
    await expect(page.locator('.stash-filter-options').getByRole('checkbox',{name:'Special',exact:true})).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('projection-status')).toContainText('please wait')
    hold=false
    await expect(page.getByTestId('projection-status')).toHaveText('Analysis is up to date.',{timeout:15000})
    await goSection(page,'Summary')
    await expect(page.locator('.overview-cards article').first()).toContainText('1')
    await goSection(page,'System settings')
    await page.getByRole('checkbox',{name:'Include stash Main',exact:true}).check()
    await page.getByRole('button',{name:'Save settings and rebuild'}).click()
    await expect(page.getByTestId('projection-status')).toHaveText('Analysis is up to date.',{timeout:15000})
    await goSection(page,'History')
    await expect(page.locator('.result-count')).toContainText('Results: 60')
  } finally {hold=false;await restore(request)}
})

test('unchanged settings finish immediately and report-read failures do not leave an endless waiting status',async({page,request})=>{
  let fail=false
  await page.route('**/quantities?*',route=>fail?route.fulfill({status:503,json:{error:'database_unavailable'}}):route.continue())
  try {
    await page.goto(path+'&section=configuration')
    const save=page.getByRole('button',{name:'Save settings and rebuild'})
    await save.click()
    await expect(page.getByTestId('projection-status')).toHaveText('Analysis is up to date.',{timeout:15000})
    fail=true
    await save.click()
    await expect(page.getByTestId('projection-status')).toContainText('could not be updated',{timeout:15000})
    await expect(page.getByTestId('projection-status')).toHaveAttribute('role','alert')
    fail=false
    await page.getByRole('button',{name:'Refresh view',exact:true}).click()
    await expect(page.getByTestId('projection-status')).toHaveText('Analysis is up to date.',{timeout:15000})
  } finally {fail=false;await restore(request)}
})

test('league timezone applies to date filters, chart range and diagnostics labels',async({page,request})=>{
  try {
    await page.goto(path+'&section=settings')
    await page.getByLabel('Display timezone',{exact:true}).fill('UTC+13')
    await page.getByRole('button',{name:'Save preferences'}).click()
    await expect(page.getByTestId('client-settings')).toContainText('Preferences saved for this browser.')
    await goSection(page,'History')
    await page.getByLabel('From day (UTC+13:00)',{exact:true}).fill('2026-01-02')
    await page.getByLabel('To day (UTC+13:00)',{exact:true}).fill('2026-01-02')
    await page.getByRole('button',{name:'Apply filters',exact:true}).click()
    await expect(page.locator('.result-count')).toContainText('Results: 30')
    await expect(page.locator('.history-transactions tbody tr').first()).toContainText('Jan 2, 2026, 1:00 AM')
    await goSection(page,'Summary')
    const chart=page.getByTestId('quantity-chart')
    await expect(chart.getByRole('img')).toBeVisible()
    await zoomTime(page)
    await expect(page.getByLabel('From day (UTC+13:00)',{exact:true})).toHaveValue('2026-01-02')
    await expect(page.getByLabel('To day (UTC+13:00)',{exact:true})).toHaveValue('2026-01-02')
    await page.getByRole('link',{name:'Diagnostics',exact:true}).click()
    await expect(page.locator('.refresh-facts')).toContainText('UTC+13:00')
    await expect(page.locator('main > footer')).toContainText('UTC+13:00')
  } finally {await restore(request)}
})

test('12/24 hour setting applies to history, chart and diagnostics without rebuilding quantities',async({page,request})=>{
  try{
    await page.goto(path+'&section=settings')
    await expect(page.getByLabel('Time format',{exact:true})).toBeVisible()
    const league=new URL(page.url()).searchParams.get('league'),endpoint=`/poe2guild/api/leagues/${league}`
    await expect.poll(async()=>(await(await request.get(endpoint+'/quantities')).json()).projection?.state,{timeout:15000}).toBe('ready')
    const original=await(await request.get(endpoint+'/quantities')).json()
    await page.getByLabel('Time format',{exact:true}).selectOption('24')
    await page.getByRole('button',{name:'Save preferences'}).click()
    await expect(page.getByTestId('client-settings')).toContainText('Preferences saved for this browser.')
    const after=await(await request.get(endpoint+'/quantities')).json()
    expect(after.projection.id).toBe(original.projection.id)
    await goSection(page,'History')
    await expect(page.locator('.history-transactions tbody tr').first().locator('td').first()).toContainText('12:00')
    await expect(page.locator('.history-transactions tbody tr').first().locator('td').first()).not.toContainText(/AM|PM/)
    await goSection(page,'Summary');await expect(page.getByTestId('time-series-chart')).toBeVisible()
    await expect(page.getByTestId('time-series-chart').locator('svg')).not.toContainText(/AM|PM/)
    await goSection(page,'Settings')
    await page.getByLabel('Time format',{exact:true}).selectOption('12')
    await page.getByRole('button',{name:'Save preferences'}).click()
    await expect(page.getByTestId('client-settings')).toContainText('Preferences saved for this browser.')
    await goSection(page,'History')
    await expect(page.locator('.history-transactions tbody tr').first().locator('td').first()).toContainText('PM')
    await page.getByRole('link',{name:'Diagnostics',exact:true}).click()
    await expect(page.locator('.refresh-facts')).toContainText(/AM|PM/)
    await page.reload()
    await page.getByRole('link',{name:'Workspace',exact:true}).click()
    await goSection(page,'Settings')
    await expect(page.getByLabel('Time format',{exact:true})).toHaveValue('12')
  }finally{await restore(request)}
})

test('Removed explanations show both attributed items, ignored empty withdrawals and a known stack with invalid source quantity',async({page})=>{
  await page.route('**/transactions?*',async route=>{
    const response=await route.fetch(),data=await response.json()
    const quantity={item_name:"Olroth's Saga",before_item:'Verisium',quantity_before:1000,quantity_after:0,
      quantity_delta:null,effective_action:'mixed',confidence:'inferred',resolution_reason:'removed_state_conflict',
      movements:[{item_name:"Olroth's Saga",quantity_delta:4,confidence:'inferred',entry_kind:'reconstruction'},{item_name:'Verisium',quantity_delta:-1000,confidence:'inferred',entry_kind:'operation'},{item_name:"Olroth's Saga",quantity_delta:-4,confidence:'source',entry_kind:'operation'}]}
    data.rows[0]={...data.rows[0],action:'removed',account:'Collector',item:"4× Olroth's Saga",quantity}
    data.rows[1]={...data.rows[1],action:'removed',quantity:{...quantity,before_item:null,quantity_before:0,quantity_delta:0,effective_action:'unchanged',resolution_reason:'removed_empty_ignored',movements:[]}}
    data.rows[2]={...data.rows[2],action:'removed',quantity:{...quantity,effective_action:'removed',resolution_reason:'invalid_quantity',movements:[{item_name:'Verisium',quantity_delta:-1000,confidence:'inferred'}]}}
    await route.fulfill({json:data})
  })
  await gotoHistory(page,path)
  const rows=page.locator('.history-transactions tbody tr')
  await expect(rows.nth(0)).toContainText('Collector')
  await expect(rows.nth(0).locator('.quantity-delta')).toContainText("Reconstruction corrections: +4 Olroth's Saga")
  await expect(rows.nth(0).locator('.quantity-delta')).toContainText('-1,000 Verisium')
  await expect(rows.nth(0).locator('.quantity-delta')).toContainText("-4 Olroth's Saga")
  await rows.nth(0).getByText('Calculation basis',{exact:true}).click()
  await expect(rows.nth(0)).toContainText('Temporary rule: clear the entire tracked stack')
  await expect(rows.nth(1).locator('.quantity-delta')).toHaveText('0')
  await rows.nth(1).getByText('Calculation basis',{exact:true}).click()
  await expect(rows.nth(1)).toContainText('slot is already empty')
  await expect(rows.nth(2).locator('.quantity-delta')).toHaveText('-1,000 Verisium')
  await page.getByRole('combobox',{name:'Language',exact:true}).selectOption('pl')
  await expect(rows.nth(1)).toContainText('slot jest już pusty')
})
