import {test,expect} from '@playwright/test'
import {goSection} from './workspace-helpers'
test.use({locale:'en-US'})
const path='/poe2guild/?lang=en'
const chart=(page:import('@playwright/test').Page)=>page.getByTestId('quantity-chart')

test('balance chart is compact and group series differ between Players and Stashes',async({page})=>{
  await page.setViewportSize({width:1440,height:1000})
  await page.goto(path)
  await expect(chart(page).getByRole('img')).toBeVisible()
  expect((await page.locator('.shell').boundingBox())!.width).toBeGreaterThan(1350)
  expect((await page.getByTestId('time-series-chart').boundingBox())!.y).toBeLessThan(320)
  await expect(page.getByRole('button',{name:'Synchronization status'})).toHaveCount(0)
  await expect(page.locator('header').getByRole('button',{name:'Refresh view',exact:true})).toBeVisible()
  await expect(page.getByTestId('report-info')).not.toHaveAttribute('open','')
  await expect(chart(page).getByRole('checkbox',{name:'Added series'})).toHaveCount(0)
  await goSection(page,'Players')
  await expect(chart(page).locator('.chart-series-picker')).toBeVisible()
  await chart(page).locator('.chart-series-picker > summary').click()
  await expect(chart(page).getByRole('checkbox',{name:'Synthetic Alice',exact:true})).toBeVisible()
  await expect(chart(page).getByRole('checkbox',{name:'Żółw',exact:true})).toBeVisible()
  await goSection(page,'Stashes')
  const league=new URL(page.url()).searchParams.get('league')
  const data=await(await page.request.get(`/poe2guild/api/leagues/${league}/quantity-series?view=stashes&series_item=Rites%20Token`)).json()
  expect(data.series.map((s:{name:string})=>s.name)).toEqual(['Main'])
  await expect(chart(page).getByRole('img')).toBeVisible()
  await page.screenshot({path:'test-results/phase-5-compact-desktop.png',fullPage:false})
})

test('wheel zoom requests a finer viewport, tooltip works and refresh preserves grouped selection',async({page})=>{
  let requested=''
  page.on('request',request=>{if(request.url().includes('/quantity-series?'))requested=request.url()})
  await page.goto(path+'&section=players')
  const graph=page.getByTestId('time-series-chart')
  await expect(graph).toBeVisible()
  await chart(page).locator('.chart-series-picker > summary').click()
  await chart(page).getByRole('checkbox',{name:'Synthetic Alice',exact:true}).uncheck()
  await chart(page).locator('.chart-series-picker > summary').click()
  const box=(await graph.boundingBox())!
  await page.mouse.move(box.x+box.width*.6,box.y+box.height*.4)
  await expect(graph.locator('svg')).toContainText('Żółw')
  await page.mouse.wheel(0,-350)
  await expect(page).toHaveURL(/chart_from=/)
  await expect.poll(()=>requested).toContain('window_start=')
  const from=new URL(page.url()).searchParams.get('chart_from')
  await page.getByRole('button',{name:'Refresh view',exact:true}).click()
  await expect(graph).toBeVisible()
  expect(new URL(page.url()).searchParams.get('chart_from')).toBe(from)
  await chart(page).locator('.chart-series-picker > summary').click()
  await expect(chart(page).getByRole('checkbox',{name:'Synthetic Alice',exact:true})).not.toBeChecked()
  await chart(page).locator('.chart-series-picker > summary').click()
  await chart(page).getByRole('button',{name:'Reset view',exact:true}).click()
  await expect(page).not.toHaveURL(/chart_from=/)
})

test('chart, table and information collapse independently and survive reload',async({page})=>{
  await page.goto(path)
  await expect(chart(page).getByRole('img')).toBeVisible()
  await chart(page).locator(':scope > summary').click()
  await expect(chart(page).getByRole('img')).toBeHidden()
  await expect(page.locator('.quantity-table')).toBeVisible()
  await page.getByTestId('quantity-table-container').locator(':scope > summary').click()
  await expect(page.locator('.quantity-table')).toBeHidden()
  await page.getByTestId('report-info').locator(':scope > summary').click()
  await expect(page.locator('.overview-cards')).toBeVisible()
  await page.reload()
  await expect(chart(page)).toBeVisible()
  await expect(chart(page)).not.toHaveAttribute('open','')
  await expect(page.getByTestId('quantity-table-container')).not.toHaveAttribute('open','')
  await expect(page.getByTestId('report-info')).toHaveAttribute('open','')
  await chart(page).locator(':scope > summary').click()
  await expect(chart(page).getByRole('img')).toBeVisible()
})

test('zoom range applies local calendar dates and league changes reset chart context',async({page})=>{
  await page.goto(path)
  await expect(chart(page).getByRole('img')).toBeVisible()
  await chart(page).getByRole('button',{name:'Zoom in',exact:true}).click()
  await chart(page).getByRole('button',{name:'Apply range to filters',exact:true}).click()
  await expect(page.getByLabel('From day (UTC)')).not.toHaveValue('')
  await goSection(page,'History')
  await expect(page.locator('.result-count')).toBeVisible()
  await goSection(page,'Summary')
  await expect(chart(page).getByRole('img')).toBeVisible()
  await page.getByRole('combobox',{name:'League',exact:true}).click()
  await page.getByRole('option',{name:'Runes of Aldur',exact:false}).click()
  await expect(chart(page).getByLabel('Chart item',{exact:true})).toHaveValue('Aldur Token')
  await expect(page).not.toHaveURL(/chart_from=/)
})

test('chart retry and PL mobile stay inside viewport',async({page})=>{
  let fail=false
  await page.route('**/quantity-series?*',route=>fail?route.fulfill({status:503,json:{error:'database_unavailable'}}):route.continue())
  await page.goto(path);await expect(chart(page).getByRole('img')).toBeVisible()
  fail=true;await chart(page).getByRole('button',{name:'Refresh chart',exact:true}).click()
  await expect(chart(page).getByRole('alert')).toContainText('database is unavailable')
  fail=false;await chart(page).getByRole('button',{name:'Refresh chart',exact:true}).click()
  await expect(chart(page).getByRole('alert')).toHaveCount(0)
  await page.getByRole('combobox',{name:'Language',exact:true}).selectOption('pl')
  await page.setViewportSize({width:390,height:844})
  await expect(chart(page).getByRole('img')).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:'test-results/phase-5-compact-mobile.png',fullPage:true})
})

test('a late coarse viewport response cannot replace newer zoom details',async({page})=>{
  let release:()=>void=()=>{},held=false,finished:()=>void=()=>{}
  const gate=new Promise<void>(resolve=>{release=resolve}),done=new Promise<void>(resolve=>{finished=resolve})
  await page.route('**/quantity-series?*',async route=>{
    if(route.request().url().includes('window_start=')&&!held){
      held=true
      const response=await route.fetch();await gate
      await route.fulfill({response}).catch(()=>{});finished()
    }else await route.continue()
  })
  try{
    await page.goto(path)
    await expect(chart(page).getByRole('img')).toBeVisible()
    await chart(page).getByRole('button',{name:'Zoom in',exact:true}).click()
    await expect.poll(()=>held).toBe(true)
    await chart(page).getByRole('button',{name:'Zoom in',exact:true}).click()
    const from=Number(new URL(page.url()).searchParams.get('chart_from'))
    await chart(page).locator('.chart-info > summary').click()
    await chart(page).getByText('Show chart data',{exact:true}).click()
    const expected=new Intl.DateTimeFormat('en',{dateStyle:'medium',timeStyle:'short',timeZone:'UTC'}).format(new Date(from))
    await expect(chart(page).locator('.chart-data tbody tr').first().locator('td').nth(1)).toHaveText(expected)
    release();await done
    await expect(chart(page).locator('.chart-data tbody tr').first().locator('td').nth(1)).toHaveText(expected)
  }finally{release()}
})
