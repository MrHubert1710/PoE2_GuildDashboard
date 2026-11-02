import { test, expect } from '@playwright/test'
import { goSection } from './workspace-helpers'
test.use({locale:'en-US'})
const path='/poe2guild/?lang=en'
const chart=(page: import('@playwright/test').Page)=>page.getByTestId('quantity-chart')

test('interactive chart shows one item, bounded data and the same totals as the report',async({page})=>{
  let points=0
  page.on('response',async response=>{if(response.url().includes('/quantity-series?')){const data=await response.json();points=data.points.length}})
  await page.goto(path)
  await expect(chart(page).getByRole('img')).toBeVisible()
  await expect(chart(page).locator('svg')).toBeVisible()
  expect(points).toBeGreaterThan(0);expect(points).toBeLessThanOrEqual(240)
  await chart(page).screenshot({path:'test-results/phase-5-chart-desktop.png'})
  await expect(chart(page).getByLabel('Chart item',{exact:true})).toHaveValue('Rites Token')
  await chart(page).getByText('Show chart data',{exact:true}).click()
  await expect(chart(page).locator('tbody tr')).toHaveCount(points)
  await page.getByLabel('Player',{exact:true}).fill('Synthetic Alice')
  await page.getByRole('button',{name:'Apply filters',exact:true}).click()
  await expect(chart(page).getByRole('img')).toBeVisible()
  const data=await(await page.request.get('/poe2guild/api/leagues/'+new URL(page.url()).searchParams.get('league')+'/quantity-series?account=Synthetic+Alice&series_item=Rites+Token')).json()
  await expect(chart(page).getByTestId('chart-totals')).toContainText('added '+data.totals.added)
  await expect(chart(page).getByTestId('chart-totals')).toContainText('removed '+data.totals.removed)
})

test('zoom, series choice, refresh, navigation, reload and reset preserve the intended chart view',async({page})=>{
  await page.goto(path)
  await expect(chart(page).getByRole('img')).toBeVisible()
  await chart(page).getByRole('button',{name:'Zoom in',exact:true}).click()
  await expect(page).toHaveURL(/chart_from=/)
  const from=new URL(page.url()).searchParams.get('chart_from'), to=new URL(page.url()).searchParams.get('chart_to')
  await chart(page).getByRole('checkbox',{name:'Removed series',exact:true}).uncheck()
  await chart(page).getByRole('button',{name:'Refresh chart',exact:true}).click()
  await expect(chart(page).getByRole('img')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('chart_from')).toBe(from)
  expect(new URL(page.url()).searchParams.get('chart_to')).toBe(to)
  await page.getByRole('button',{name:'Refresh view',exact:true}).click()
  await expect(chart(page).getByRole('img')).toBeVisible()
  await goSection(page,'History');await goSection(page,'Players')
  await expect(chart(page).getByRole('img')).toBeVisible()
  await page.reload()
  await expect(chart(page).getByRole('checkbox',{name:'Removed series',exact:true})).not.toBeChecked()
  expect(new URL(page.url()).searchParams.get('chart_from')).toBe(from)
  await chart(page).getByRole('button',{name:'Reset view',exact:true}).click()
  await expect(page).not.toHaveURL(/chart_from=/)
  await expect(chart(page).getByRole('button',{name:'Apply range to filters',exact:true})).toBeDisabled()
})

test('zoomed chart range applies UTC days to shared history and report filters',async({page})=>{
  await page.goto(path)
  await expect(chart(page).getByRole('img')).toBeVisible()
  await chart(page).getByRole('button',{name:'Zoom in',exact:true}).click()
  await chart(page).getByRole('button',{name:'Zoom in',exact:true}).click()
  await chart(page).getByRole('button',{name:'Apply range to filters',exact:true}).click()
  const params=new URL(page.url()).searchParams
  expect(params.get('from')).toMatch(/^2026-01-0[12]$/)
  expect(params.get('to')).toMatch(/^2026-01-0[12]$/)
  await expect(page.getByLabel('From day (UTC)')).toHaveValue(params.get('from')!)
  await goSection(page,'History')
  await expect(page.locator('.result-count')).toContainText('Results:')
  expect(new URL(page.url()).searchParams.get('from')).toBe(params.get('from'))
})

test('league changes, empty matches, retry and PL/mobile chart are isolated',async({page})=>{
  let fail=false
  await page.route('**/quantity-series?*',route=>fail?route.fulfill({status:503,json:{error:'database_unavailable'}}):route.continue())
  await page.goto(path)
  await expect(chart(page).getByRole('img')).toBeVisible()
  await page.getByRole('combobox',{name:'League',exact:true}).click()
  await page.getByRole('option',{name:'Runes of Aldur',exact:false}).click()
  await expect(chart(page).getByLabel('Chart item',{exact:true})).toHaveValue('Aldur Token')
  fail=true
  await chart(page).getByRole('button',{name:'Refresh chart',exact:true}).click()
  await expect(chart(page).getByRole('alert')).toContainText('database is unavailable')
  fail=false
  await chart(page).getByRole('button',{name:'Refresh chart',exact:true}).click()
  await expect(chart(page).getByRole('img')).toBeVisible()
  await page.getByRole('combobox',{name:'Language',exact:true}).selectOption('pl')
  await page.setViewportSize({width:390,height:844})
  await expect(chart(page).getByRole('img')).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:'test-results/phase-5-mobile.png',fullPage:true})
  await page.getByLabel('Gracz',{exact:true}).fill('No such player')
  await page.getByRole('button',{name:'Zastosuj filtry',exact:true}).click()
  await expect(chart(page)).toContainText('Brak ruchów')
})


test('real pointer tooltip, wheel zoom and drag panning change the chart without refetching history',async({page})=>{
  let sourceRequests=0
  page.on('request',request=>{if(request.url().includes('/transactions?'))sourceRequests++})
  await page.goto(path)
  const graph=page.getByTestId('time-series-chart')
  await expect(graph).toBeVisible()
  await graph.scrollIntoViewIfNeeded()
  const box=(await graph.boundingBox())!
  await page.mouse.move(box.x+box.width*0.6,box.y+box.height*0.4)
  await expect(graph.locator('svg')).toContainText('Added')
  const before=sourceRequests
  await page.mouse.wheel(0,-450)
  await expect(page).toHaveURL(/chart_from=/)
  const from=new URL(page.url()).searchParams.get('chart_from')
  await page.mouse.move(box.x+box.width*0.6,box.y+box.height*0.4)
  await page.mouse.down()
  await page.mouse.move(box.x+box.width*0.75,box.y+box.height*0.4,{steps:8})
  await page.mouse.up()
  await expect.poll(()=>new URL(page.url()).searchParams.get('chart_from')).not.toBe(from)
  expect(sourceRequests).toBe(before)
})

test('item changes have back/forward history and league changes retire the previous chart context',async({page})=>{
  await page.goto(path)
  const item=chart(page).getByLabel('Chart item',{exact:true})
  await expect(item).toHaveValue('Rites Token')
  await item.selectOption('Literal %_ Item')
  await expect(page).toHaveURL(/chart_item=/)
  await expect(item).toHaveValue('Literal %_ Item')
  await page.goBack()
  await expect(item).toHaveValue('Rites Token')
  await page.goForward()
  await expect(item).toHaveValue('Literal %_ Item')
  await chart(page).getByRole('button',{name:'Zoom in',exact:true}).click()
  await page.getByRole('combobox',{name:'League',exact:true}).click()
  await page.getByRole('option',{name:'Runes of Aldur',exact:false}).click()
  await expect(item).toHaveValue('Aldur Token')
  await expect(page).not.toHaveURL(/chart_item=|chart_from=/)
})

test('history alone does not load ECharts and late chart responses cannot overwrite another league',async({page})=>{
  let chunks=0,requests=0,first=true,release:()=>void=()=>{}
  const gate=new Promise<void>(resolve=>{release=resolve})
  page.on('request',request=>{if(request.url().includes('/TimeSeriesChart-'))chunks++;if(request.url().includes('/quantity-series?'))requests++})
  await page.route('**/quantity-series?*',async route=>{
    if(first){first=false;await gate}
    await route.continue().catch(()=>{})
  })
  try {
    await page.goto(path+'&section=history')
    await expect(page.locator('.result-count')).toContainText('Results: 60')
    expect(chunks).toBe(0);expect(requests).toBe(0)
    await goSection(page,'Summary')
    await expect.poll(()=>requests).toBe(1)
    await page.getByRole('combobox',{name:'League',exact:true}).click()
    await page.getByRole('option',{name:'Runes of Aldur',exact:false}).click()
    await expect(chart(page).getByLabel('Chart item',{exact:true})).toHaveValue('Aldur Token')
    release()
    await expect(chart(page).getByRole('img')).toBeVisible()
    await expect(chart(page).getByLabel('Chart item',{exact:true})).toHaveValue('Aldur Token')
  } finally {release()}
})
