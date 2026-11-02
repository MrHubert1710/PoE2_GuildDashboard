import {test,expect} from './fixtures'
import type {Locator} from './fixtures'
import {goSection,zoomTime,zoomValues,resetTime,resetValues} from './workspace-helpers'
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
  await expect(chart(page).getByTestId('chart-legend')).toBeVisible()
  await expect(chart(page).getByRole('checkbox',{name:'Synthetic Alice',exact:true})).toBeVisible()
  await expect(chart(page).getByRole('checkbox',{name:'Żółw',exact:true})).toBeVisible()
  const beams=page.getByTestId('value-navigator').getByTestId('value-series-beam')
  const legend=chart(page).getByTestId('chart-legend')
  await expect(beams).toHaveCount(await legend.getByRole('checkbox').count())
  expect(await beams.count()).toBeGreaterThan(1)
  for(let index=0;index<await beams.count();index++){
    expect(await beams.nth(index).evaluate(element=>getComputedStyle(element).stroke)).toBe(await legend.locator('.series-swatch').nth(index).evaluate(element=>getComputedStyle(element).backgroundColor))
    expect(Number(await beams.nth(index).getAttribute('data-min'))).toBeLessThanOrEqual(Number(await beams.nth(index).getAttribute('data-max')))
  }
  await legend.getByRole('checkbox',{name:'Synthetic Alice',exact:true}).uncheck()
  await expect(beams).toHaveCount(await legend.getByRole('checkbox').count()-1)
  await expect(page.getByTestId('value-navigator').locator('[data-series-name="Synthetic Alice"]')).toHaveCount(0)

  await goSection(page,'Stashes')
  const league=new URL(page.url()).searchParams.get('league')
  const data=await(await page.request.get(`/poe2guild/api/leagues/${league}/quantity-series?view=stashes&series_item=Rites%20Token`)).json()
  expect(data.series.map((s:{name:string})=>s.name)).toEqual(['Main'])
  await expect(chart(page).getByRole('img')).toBeVisible()
  await page.screenshot({path:'test-results/phase-5-compact-desktop.png',fullPage:false})
})

test('miniature zoom requests a finer viewport, tooltip works and refresh preserves grouped selection',async({page})=>{
  let requested=''
  page.on('request',request=>{if(request.url().includes('/quantity-series?'))requested=request.url()})
  await page.goto(path+'&section=players')
  const graph=page.getByTestId('time-series-chart')
  await expect(graph).toBeVisible()
  await chart(page).getByRole('checkbox',{name:'Synthetic Alice',exact:true}).uncheck()
  const box=(await graph.boundingBox())!
  await page.mouse.move(box.x+box.width*.6,box.y+box.height*.4)
  await expect(page.getByRole('tooltip')).toContainText('Żółw')
  await zoomTime(page)
  await expect(page).toHaveURL(/chart_from=/)
  await expect.poll(()=>requested).toContain('window_start=')
  const from=new URL(page.url()).searchParams.get('chart_from')
  await page.getByRole('button',{name:'Refresh view',exact:true}).click()
  await expect(graph).toBeVisible()
  expect(new URL(page.url()).searchParams.get('chart_from')).toBe(from)
  await expect(chart(page).getByRole('checkbox',{name:'Synthetic Alice',exact:true})).not.toBeChecked()
  await resetTime(page)
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
  await zoomTime(page)
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
    await zoomTime(page)
    await expect.poll(()=>held).toBe(true)
    await zoomTime(page)
    const from=Number(new URL(page.url()).searchParams.get('chart_from'))
    await chart(page).locator('.chart-info > summary').click()
    await chart(page).getByText('Show chart data',{exact:true}).click()
    const expected=new Intl.DateTimeFormat('en',{dateStyle:'medium',timeStyle:'short',timeZone:'UTC'}).format(new Date(from))
    await expect(chart(page).locator('.chart-data tbody tr').first().locator('td').nth(1)).toHaveText(expected)
    release();await done
    await expect(chart(page).locator('.chart-data tbody tr').first().locator('td').nth(1)).toHaveText(expected)
  }finally{release()}
})

test('navigator centers the local overview and synchronizes selected days at both ends of the domain',async({page})=>{
  await page.goto(path)
  const graph=page.getByTestId('time-series-chart'),navigator=page.getByTestId('series-navigator')
  await expect(graph).toBeVisible()
  for(let index=0;index<3;index++)await zoomTime(page)
  const fullEnd=Number(await navigator.getAttribute('data-domain-end'))
  const width=Number(await navigator.getAttribute('data-window-end'))-Number(await navigator.getAttribute('data-window-start'))
  const response=page.waitForResponse(r=>r.url().includes('/quantity-series?')&&r.url().includes('window_start='+String(fullEnd-width)))
  await page.getByRole('slider',{name:'Chart overview range',exact:true}).press('End')
  const data=await(await response).json()
  expect(data.series[0].event_count).toBe(30)
  expect(data.series[0].closing_balance).toBe(63)
  await expect(page.getByLabel('From day (UTC)',{exact:true})).toHaveValue('2026-01-02')
  await expect(page.getByLabel('To day (UTC)',{exact:true})).toHaveValue('2026-01-02')
  expect(await graph.getAttribute('data-window-start')).toBe(await navigator.getAttribute('data-window-start'))
  expect(await graph.getAttribute('data-window-end')).toBe(await navigator.getAttribute('data-window-end'))
  await expectCentered(navigator)
  await page.getByRole('slider',{name:'Chart overview range',exact:true}).press('Home')
  await expect(page.getByLabel('From day (UTC)',{exact:true})).toHaveValue('2026-01-01')
  await expect(page.getByLabel('To day (UTC)',{exact:true})).toHaveValue('2026-01-01')
  await expectCentered(navigator)
  await resetTime(page)
  await expect(page.getByLabel('From day (UTC)',{exact:true})).toHaveValue('')
  await expect(page.getByLabel('To day (UTC)',{exact:true})).toHaveValue('')
})

test('repeated miniature pans load detail beyond the original central window and keep navigator aligned',async({page})=>{
  await page.goto(path)
  const graph=page.getByTestId('time-series-chart'),navigator=page.getByTestId('series-navigator')
  await expect(graph).toBeVisible()
  for(let index=0;index<3;index++)await zoomTime(page)
  const fullEnd=Number(await navigator.getAttribute('data-domain-end'))
  const width=Number(await navigator.getAttribute('data-window-end'))-Number(await navigator.getAttribute('data-window-start'))
  const response=page.waitForResponse(r=>r.url().includes('/quantity-series?')&&r.url().includes('window_start='+String(fullEnd-width)))
  const box=(await navigator.locator('svg').boundingBox())!
  for(let index=0;index<9;index++){
    await expectCentered(navigator)
    await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5)
    await page.mouse.down();await page.mouse.move(box.x+box.width*.8,box.y+box.height*.5,{steps:3});await page.mouse.up()
  }
  const data=await(await response).json()
  expect(data.series[0].event_count).toBe(30)
  expect(data.series[0].closing_balance).toBe(63)
  expect(data.sampled).toBe(false)
  expect(await graph.getAttribute('data-window-start')).toBe(await navigator.getAttribute('data-window-start'))
  await expectCentered(navigator)
  await expect(page.getByLabel('From day (UTC)',{exact:true})).toHaveValue('2026-01-02')
})

test('linked dates and manual dates select time without restricting either navigator',async({page})=>{
  await page.goto(path+'&from=2026-01-01&to=2026-01-02')
  const graph=page.getByTestId('time-series-chart'),navigator=page.getByTestId('series-navigator')
  await expect(graph).toBeVisible()
  const start=await navigator.getAttribute('data-domain-start'),end=await navigator.getAttribute('data-domain-end')
  for(let i=0;i<3;i++)await zoomTime(page)
  await page.getByRole('slider',{name:'Chart overview range',exact:true}).press('End')
  await expect(page.getByLabel('From day (UTC)',{exact:true})).toHaveValue('2026-01-02')
  await page.reload();await expect(graph).toBeVisible()
  expect(await navigator.getAttribute('data-domain-start')).toBe(start)
  expect(await navigator.getAttribute('data-domain-end')).toBe(end)
  await page.getByLabel('From day (UTC)',{exact:true}).fill('2026-01-01')
  await page.getByLabel('To day (UTC)',{exact:true}).fill('2026-01-01')
  await page.getByRole('button',{name:'Apply filters',exact:true}).click()
  await expect(page).not.toHaveURL(/chart_base_from=|chart_from=/)
  await expect(graph).toBeVisible()
  expect(await navigator.getAttribute('data-domain-start')).toBe(start)
  expect(await navigator.getAttribute('data-domain-end')).toBe(end)
  await expect(page.getByLabel('From day (UTC)',{exact:true})).toHaveValue('2026-01-01')
  const later=page.waitForResponse(r=>r.url().includes('/quantity-series?')&&r.url().includes('window_start='))
  await page.getByRole('slider',{name:'Chart overview range',exact:true}).press('End')
  await later
  await expect(page.getByLabel('To day (UTC)',{exact:true})).toHaveValue('2026-01-02')
})

test('vertical value navigator zooms and pans independently of time and survives refresh and reload',async({page})=>{
  let requests=0
  page.on('request',request=>{if(request.url().includes('/quantity-series?'))requests++})
  await page.goto(path);const graph=page.getByTestId('time-series-chart'),values=page.getByTestId('value-navigator')
  await expect(graph).toBeVisible();await expect(values).toBeVisible()
  expect(Math.abs((await values.boundingBox())!.height-(await graph.boundingBox())!.height)).toBeLessThan(2)
  expect((await page.getByTestId('series-navigator').boundingBox())!.y-(await graph.boundingBox())!.y).toBeLessThan(500)
  await expect(values.getByTestId('value-series-beam')).toHaveCount(1)
  await expect(values.getByTestId('value-series-beam')).toHaveAttribute('data-min','0')
  await expect(values.getByTestId('value-series-beam')).toHaveAttribute('data-max','63')
  await expect(values.locator('.navigator-value-window')).toHaveCSS('fill','rgba(145, 169, 220, 0.2)')
  const paths=await page.getByTestId('series-navigator').getByTestId('navigator-series').evaluateAll(elements=>elements.map(element=>element.getAttribute('d')!))
  for(const path of paths)for(const match of path.matchAll(/(?:M[-\d.]+,|V)([-\d.]+)/g)){
    expect(Number(match[1])).toBeGreaterThanOrEqual(8)
    expect(Number(match[1])).toBeLessThanOrEqual(26)
  }
  const timeStart=await graph.getAttribute('data-window-start'),timeEnd=await graph.getAttribute('data-window-end')
  const before=requests,initialMin=Number(await graph.getAttribute('data-value-min')),initialMax=Number(await graph.getAttribute('data-value-max'))
  await zoomValues(page)
  await expect(page).toHaveURL(/chart_ymin=/)
  const yMin=await graph.getAttribute('data-value-min'),yMax=await graph.getAttribute('data-value-max')
  expect(Number(yMax)-Number(yMin)).toBeLessThan(initialMax-initialMin)
  expect(await values.getAttribute('data-value-min')).toBe(yMin)
  expect(await values.getAttribute('data-value-max')).toBe(yMax)
  expect(await graph.getAttribute('data-window-start')).toBe(timeStart)
  expect(await graph.getAttribute('data-window-end')).toBe(timeEnd)
  expect(requests).toBe(before)
  const handle=(await page.getByRole('slider',{name:'Minimum chart value',exact:true}).boundingBox())!
  await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2);await page.mouse.down()
  await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2-12,{steps:4});await page.mouse.up()
  expect(Number(await graph.getAttribute('data-value-min'))).toBeGreaterThan(Number(yMin))
  expect(await graph.getAttribute('data-value-max')).toBe(yMax)
  await page.getByRole('slider',{name:'Chart value range',exact:true}).press('Home')
  expect(Number(await graph.getAttribute('data-value-min'))).toBeGreaterThan(Number(yMin))
  const moved=await graph.getAttribute('data-value-min')
  await page.getByRole('button',{name:'Refresh view',exact:true}).click();await expect(graph).toBeVisible()
  expect(await graph.getAttribute('data-value-min')).toBe(moved)
  await page.reload();await expect(graph).toBeVisible()
  expect(await graph.getAttribute('data-value-min')).toBe(moved)
  await resetValues(page)
  await expect(page).not.toHaveURL(/chart_ymin=|chart_ymax=/)
  await page.setViewportSize({width:390,height:844})
  await expect(values).toBeVisible()
  expect(Math.abs((await values.boundingBox())!.height-(await graph.boundingBox())!.height)).toBeLessThan(2)
  expect((await page.getByTestId('series-navigator').boundingBox())!.y-(await graph.boundingBox())!.y).toBeLessThan(500)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:'test-results/phase-5-value-navigator.png',fullPage:false})
})

async function expectCentered(navigator: Locator) {
  const selection=navigator.getByTestId('navigator-window')
  await expect.poll(async()=>Math.abs(Number(await selection.getAttribute('x'))-350)).toBeLessThan(.001)
  await expect.poll(async()=>Math.abs(Number(await selection.getAttribute('width'))-300)).toBeLessThan(.001)
}

test('time navigator freezes context while dragging and animates back to the central 30 percent',async({page})=>{
  await page.goto(path)
  const navigator=page.getByTestId('series-navigator'),graph=page.getByTestId('time-series-chart')
  await expect(graph).toBeVisible()
  for(let i=0;i<3;i++)await zoomTime(page)
  await expectCentered(navigator)
  const selection=navigator.getByTestId('navigator-window'),box=(await navigator.locator('svg').boundingBox())!
  const domain=await navigator.getAttribute('data-display-start')
  const before=Number(await navigator.getAttribute('data-window-start'))
  await page.mouse.move(box.x+box.width*.5,box.y+box.height*.5)
  await page.mouse.down();await page.mouse.move(box.x+box.width*.65,box.y+box.height*.5,{steps:5})
  expect(await navigator.getAttribute('data-display-start')).toBe(domain)
  expect(Number(await selection.getAttribute('x'))).toBeGreaterThan(490)
  expect(Number(await navigator.getAttribute('data-window-start'))).toBeGreaterThan(before)
  await selection.evaluate(element=>{
    const samples:number[]=[]
    const observer=new MutationObserver(()=>{
      const x=Number(element.getAttribute('x'));samples.push(x)
      element.setAttribute('data-motion-samples',JSON.stringify(samples))
      if(Math.abs(x-350)<.001)observer.disconnect()
    })
    observer.observe(element,{attributes:true,attributeFilter:['x']})
  })
  await page.mouse.up();await expectCentered(navigator)
  const samples=JSON.parse((await selection.getAttribute('data-motion-samples'))!) as number[]
  expect(samples.some(value=>value>351&&value<490)).toBe(true)
  expect(await navigator.getAttribute('data-display-start')).not.toBe(domain)
  expect(await graph.getAttribute('data-window-start')).toBe(await navigator.getAttribute('data-window-start'))
  const endHandle=page.getByRole('slider',{name:'End of chart range',exact:true})
  const handle=(await endHandle.boundingBox())!
  const previousWidth=Number(await navigator.getAttribute('data-window-end'))-Number(await navigator.getAttribute('data-window-start'))
  await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2);await page.mouse.down()
  await page.mouse.move(handle.x+handle.width/2+box.width*.05,handle.y+handle.height/2,{steps:4});await page.mouse.up()
  await expectCentered(navigator)
  expect(Number(await navigator.getAttribute('data-window-end'))-Number(await navigator.getAttribute('data-window-start'))).toBeGreaterThan(previousWidth)
  await page.reload();await expect(graph).toBeVisible();await expectCentered(navigator)
  await page.emulateMedia({reducedMotion:'reduce'})
  await page.getByRole('slider',{name:'Chart overview range',exact:true}).press('Home')
  await expectCentered(navigator)
  expect(await navigator.getAttribute('data-window-start')).toBe(await navigator.getAttribute('data-domain-start'))
  await page.setViewportSize({width:390,height:844});await expectCentered(navigator)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
})

test('initial and manual day filters retain full history and value bounds in miniatures',async({page})=>{
  await page.goto(path+'&chart_item=Rites+Token&from=2026-01-01&to=2026-01-01')
  const graph=page.getByTestId('time-series-chart'),nav=page.getByTestId('series-navigator'),values=page.getByTestId('value-navigator')
  await expect(graph).toBeVisible()
  const start=await nav.getAttribute('data-domain-start'),end=await nav.getAttribute('data-domain-end')
  const minimum=await values.getAttribute('data-domain-min'),maximum=await values.getAttribute('data-domain-max')
  expect(Number(end)).toBeGreaterThan(Date.parse('2026-01-02T00:00:00Z'))
  expect(Number(await graph.getAttribute('data-window-end'))).toBe(Date.parse('2026-01-02T00:00:00Z'))
  await page.getByLabel('From day (UTC)',{exact:true}).fill('2026-01-02')
  await page.getByLabel('To day (UTC)',{exact:true}).fill('2026-01-02')
  await page.getByRole('button',{name:'Apply filters',exact:true}).click()
  await expect.poll(()=>graph.getAttribute('data-window-start')).toBe(String(Date.parse('2026-01-02T00:00:00Z')))
  expect(await nav.getAttribute('data-domain-start')).toBe(start)
  expect(await nav.getAttribute('data-domain-end')).toBe(end)
  expect(await values.getAttribute('data-domain-min')).toBe(minimum)
  expect(await values.getAttribute('data-domain-max')).toBe(maximum)
  await page.reload();await expect(graph).toBeVisible()
  expect(await values.getAttribute('data-domain-max')).toBe(maximum)
  await page.getByRole('slider',{name:'Chart overview range',exact:true}).press('Home')
  await expect(page.getByLabel('From day (UTC)',{exact:true})).toHaveValue('2026-01-01')
  await expectCentered(nav)
  expect(await nav.getAttribute('data-domain-end')).toBe(end)
  expect(await values.getAttribute('data-domain-max')).toBe(maximum)
})

test('combined balance is dashed, independently toggleable and consistent across players and stashes',async({page})=>{
  let payload:any
  page.on('response',async response=>{if(response.url().includes('/quantity-series?'))payload=await response.json()})
  await page.goto(path+'&section=players')
  const graph=page.getByTestId('time-series-chart'),legend=page.getByTestId('chart-legend')
  await expect(graph).toBeVisible()
  const combined=legend.getByRole('checkbox',{name:'Combined balance',exact:true})
  await expect(combined).toBeChecked()
  await expect(graph.locator('path[stroke-dasharray]')).not.toHaveCount(0)
  await expect.poll(()=>payload?.total_series?.closing_balance).toBe(63)
  const total=JSON.stringify(payload.total_series.points)
  await legend.getByRole('checkbox',{name:'Synthetic Alice',exact:true}).uncheck()
  await expect(combined).toBeChecked()
  expect(JSON.stringify(payload.total_series.points)).toBe(total)
  await combined.uncheck()
  await expect(graph.locator('path[stroke-dasharray]')).toHaveCount(0)
  await expect(page.getByTestId('value-navigator').locator('[data-series-id="combined"]')).toHaveCount(0)
  await combined.check();await expect(graph.locator('path[stroke-dasharray]')).not.toHaveCount(0)
  await page.reload();await expect(combined).toBeChecked()
  await goSection(page,'Stashes')
  await expect(legend.getByRole('checkbox',{name:'Combined balance',exact:true})).toBeChecked()
  await expect.poll(()=>payload?.view).toBe('stashes')
  expect(payload.total_series.closing_balance).toBe(63)
  await goSection(page,'Summary')
  await expect(legend.getByRole('checkbox')).toHaveCount(1)
  await expect(graph.locator('path[stroke-dasharray]')).not.toHaveCount(0)
})

test('player filter tooltip shows one row per series for operations sharing a timestamp',async({page})=>{
  await page.route('**/quantity-series?*',async route=>{
    const response=await route.fetch(),data=await response.json()
    if(new URL(route.request().url()).searchParams.has('at')){for(const row of data.balances??[])row.balance=29}
    if(new URL(route.request().url()).searchParams.has('account')&&data.total_series&&data.window){
      const {start,end}=data.window,middle=Math.floor((start+end)/2)
      for(const series of [...data.series,data.total_series]){
        series.points=[{timestamp:start,balance:0},{timestamp:middle,balance:11},{timestamp:middle,balance:29},{timestamp:end,balance:29}]
        series.overview=series.points
      }
    }
    await route.fulfill({response,json:data})
  })
  await page.goto(path+'&section=players')
  const graph=page.getByTestId('time-series-chart'),legend=page.getByTestId('chart-legend')
  await expect(graph).toBeVisible()
  await page.getByLabel('Player',{exact:true}).fill('Synthetic Alice')
  await page.getByRole('button',{name:'Apply filters',exact:true}).click()
  await expect(legend.getByRole('checkbox')).toHaveCount(2)
  const box=(await graph.boundingBox())!
  await page.mouse.move(box.x+65+(box.width-85)*.5,box.y+box.height*.4)
  await expect(page.getByRole('tooltip').locator('.chart-tooltip-row span').filter({hasText:/^Combined balance$/})).toHaveCount(1)
  await expect(page.getByRole('tooltip').locator('.chart-tooltip-row span').filter({hasText:/^Synthetic Alice$/})).toHaveCount(1)
  await expect(page.getByRole('tooltip').locator('strong').filter({hasText:/^29$/})).toHaveCount(2)
})

test('All sums quantities, value mode stays empty and historical pricing is locked',async({page})=>{
  await page.goto(path+'&section=players')
  const graph=page.getByTestId('time-series-chart')
  await expect(graph).toBeVisible()
  await expect(chart(page).getByRole('button',{name:/^(Zoom in|Zoom values|Reset view|Reset values)$/})).toHaveCount(0)
  await chart(page).getByLabel('Chart item',{exact:true}).selectOption('__all__')
  await expect(page).toHaveURL(/chart_item=__all__/)
  await expect(graph).toBeVisible()
  const league=new URL(page.url()).searchParams.get('league')
  const data=await(await page.request.get(`/poe2guild/api/leagues/${league}/quantity-series?view=players&all_items=1`)).json()
  expect(data.all_items).toBe(true)
  expect(data.total_series.closing_balance).toBeGreaterThan(63)
  let quantityRequests=0
  page.on('request',request=>{if(request.url().includes('/quantity-series?'))quantityRequests++})
  await page.getByRole('switch',{name:'Value mode',exact:true}).check()
  await expect(page.getByTestId('valuation-chart')).toBeVisible()
  await expect(page.getByLabel('Chart item',{exact:true})).toHaveCount(0)
  await expect(page.getByRole('switch',{name:'Current prices',exact:true})).toBeDisabled()
  await expect(page.getByRole('switch',{name:'Current prices',exact:true})).not.toBeChecked()
  await expect(graph).toHaveCount(0)
  await page.waitForTimeout(300)
  expect(quantityRequests).toBe(0)
  await page.reload();await expect(page.getByTestId('valuation-chart')).toBeVisible()
  await page.getByRole('switch',{name:'Value mode',exact:true}).uncheck()
  await expect(graph).toBeVisible()
  await expect(page.getByLabel('Chart item',{exact:true})).toHaveValue('__all__')
})

test('legend color popup changes line and range beam, persists locally and does not toggle the series',async({page})=>{
  await page.goto(path+'&section=players')
  const graph=page.getByTestId('time-series-chart'),legend=page.getByTestId('chart-legend')
  await expect(graph).toBeVisible()
  const checkbox=legend.getByRole('checkbox',{name:'Synthetic Alice',exact:true})
  await legend.getByRole('button',{name:'Color: Synthetic Alice',exact:true}).click()
  const popup=page.getByRole('dialog',{name:'Color: Synthetic Alice',exact:true})
  await expect(popup).toBeVisible()
  await popup.getByLabel('Series color',{exact:true}).fill('#ff2244')
  await popup.getByRole('button',{name:'Close',exact:true}).click()
  await expect(checkbox).toBeChecked()
  await expect(graph.locator('path[stroke="#ff2244"]')).not.toHaveCount(0)
  await expect(page.getByTestId('value-navigator').locator('[data-series-name="Synthetic Alice"]')).toHaveAttribute('stroke','#ff2244')
  await page.reload();await expect(graph).toBeVisible()
  await expect(graph.locator('path[stroke="#ff2244"]')).not.toHaveCount(0)
  await expect(checkbox).toBeChecked()
})

test('tooltip uses pointer time between snapshots, keeps state and main wheel does not zoom',async({page})=>{
  await page.goto(path+'&section=players')
  const graph=page.getByTestId('time-series-chart')
  await expect(graph).toBeVisible()
  const box=(await graph.boundingBox())!
  const start=Number(await graph.getAttribute('data-window-start')),end=Number(await graph.getAttribute('data-window-end'))
  for(const ratio of [.2,.3]){
    await page.mouse.move(box.x+65+(box.width-85)*ratio,box.y+box.height*.4)
    const tooltip=page.getByRole('tooltip')
    await expect(tooltip.locator('.chart-tooltip-row')).toHaveCount(3)
    const timestamp=Number(await tooltip.getAttribute('data-state-at'))
    expect(Math.abs(timestamp-(start+(end-start)*ratio))).toBeLessThan((end-start)*.002)
    expect(await tooltip.locator('[data-series-id="combined"] strong').textContent()).toBe('33')
  }
  await page.mouse.wheel(0,-300)
  expect(await graph.getAttribute('data-window-start')).toBe(String(start))
  expect(await graph.getAttribute('data-window-end')).toBe(String(end))
  await expect(graph.locator('svg circle')).toHaveCount(0)
})

test('automatic value-axis padding is not labelled as a real minimum or maximum',async({page})=>{
  await page.goto(path)
  const graph=page.getByTestId('time-series-chart')
  await expect(graph).toBeVisible()
  const min=Number(await graph.getAttribute('data-value-min')),max=Number(await graph.getAttribute('data-value-max'))
  expect(min).toBe(-4);expect(max).toBe(67)
  await expect(graph.locator('svg text').filter({hasText:/^-4$/})).toHaveCount(0)
  await expect(graph.locator('svg text').filter({hasText:/^67$/})).toHaveCount(0)
  await expect(graph.locator('svg text').filter({hasText:/^0$/})).toHaveCount(1)
  await expect(graph.locator('svg text').filter({hasText:/^40$/})).toHaveCount(1)
  const query=new URL(page.url());query.searchParams.set('chart_ymin','0');query.searchParams.set('chart_ymax','1')
  await page.goto(query.href);await expect(graph).toBeVisible()
  await expect(graph.locator('svg text').filter({hasText:/^1$/})).toHaveCount(1)
})

test('real extrema have labelled reference lines, negative player minima are kept and padding lines are hidden',async({page})=>{
  await page.route('**/quantity-series?*',async route=>{
    const response=await route.fetch(),data=await response.json()
    if(!new URL(route.request().url()).searchParams.has('at')&&data.window){
      for(const series of [...data.series,...data.navigator.series,...(data.total_series?[data.total_series]:[]),...(data.navigator.total_series?[data.navigator.total_series]:[])]){
        series.points=[{timestamp:data.window.start,balance:-25},{timestamp:(data.window.start+data.window.end)/2,balance:73},{timestamp:data.window.end,balance:73}]
        series.overview=series.points
      }
    }
    await route.fulfill({response,json:data})
  })
  await page.goto(path+'&section=players')
  const graph=page.getByTestId('time-series-chart')
  await expect(graph).toBeVisible()
  await expect(graph).toHaveAttribute('data-actual-min','-25')
  await expect(graph).toHaveAttribute('data-actual-max','73')
  await expect(graph.locator('svg text').filter({hasText:/^-25$/})).toHaveCount(1)
  await expect(graph.locator('svg text').filter({hasText:/^73$/})).toHaveCount(1)
  // Reference lines are independent of the source curves, with no point symbols.
  await expect(graph.locator('path[stroke="#a9bfb1"]')).toHaveCount(2)
  await expect(graph.locator('svg circle')).toHaveCount(0)
  const min=Number(await graph.getAttribute('data-value-min')),max=Number(await graph.getAttribute('data-value-max'))
  expect(min).toBeLessThan(-25);expect(max).toBeGreaterThan(73)
  const texts=await graph.locator('svg text').allTextContents()
  expect(texts).not.toContain(String(min));expect(texts).not.toContain(String(max))
})

test('technical corrections use a localized separate legend and table label',async({page})=>{
  await page.route('**/quantity-series?*',async route=>{
    const response=await route.fetch(),data=await response.json()
    if(data.view==='players'){
      for(const group of [data.series,data.navigator?.series])if(group?.length){group[0].name='__poa_reconstruction__';group[0].reconstruction=true}
    }
    await route.fulfill({json:data})
  })
  await page.route('**/quantities?*',async route=>{
    const response=await route.fetch(),data=await response.json()
    if(new URL(route.request().url()).searchParams.get('view')==='players'&&data.rows?.length){data.rows[0].account='__poa_reconstruction__';data.rows[0].reconstruction=true}
    await route.fulfill({json:data})
  })
  await page.goto(path+'&section=players')
  await expect(chart(page).getByRole('checkbox',{name:'Reconstruction corrections',exact:true})).toBeVisible()
  await expect(page.getByTestId('quantity-panel').locator('.quantity-table')).toContainText('Reconstruction corrections')
  await expect(page.getByTestId('quantity-panel')).not.toContainText('__poa_reconstruction__')
  await page.getByRole('combobox',{name:'Language',exact:true}).selectOption('pl')
  await expect(chart(page).getByRole('checkbox',{name:'Korekty rekonstrukcji',exact:true})).toBeVisible()
  await expect(page.getByTestId('quantity-panel').locator('.quantity-table')).toContainText('Korekty rekonstrukcji')
})
