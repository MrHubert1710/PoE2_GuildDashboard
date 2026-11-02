import {test,expect} from './fixtures'
import {goSection} from './workspace-helpers'
const key='path-of-accounting.preferences.v1'
const base='/poe2guild/?lang=en'

test('display preferences are local, leave server settings and projection unchanged, and preserve UTC filters across clients',async({browser,request})=>{
  const first=await browser.newContext({locale:'en-US'}),second=await browser.newContext({locale:'en-US'})
  try{
    const a=await first.newPage(),b=await second.newPage()
    const url='http://127.0.0.1:19003'+base+'&section=history&from=2026-01-01T12%3A00%3A00.000Z&to=2026-01-02T12%3A00%3A00.000Z'
    await a.goto(url);await expect(a.locator('.result-count')).toContainText('Results: 30')
    const league=new URL(a.url()).searchParams.get('league'),endpoint='/poe2guild/api/leagues/'+league
    const before=await(await request.get(endpoint+'/quantity-settings')).json()
    await expect.poll(async()=>(await(await a.request.get(endpoint+'/quantities')).json()).projection.state).toBe('ready')
    const original=await(await a.request.get(endpoint+'/quantities')).json()
    const writes:string[]=[];a.on('request',request=>{if(request.method()==='PUT'||request.url().endsWith('/refresh')&&request.method()==='POST')writes.push(request.url())})
    await goSection(a,'Settings')
    const settings=a.getByTestId('client-settings')
    await settings.getByLabel('Display timezone',{exact:true}).fill('UTC+13')
    await settings.getByLabel('Time format',{exact:true}).selectOption('24')
    await settings.getByRole('button',{name:'Save preferences',exact:true}).click()
    await expect(settings).toContainText('Preferences saved for this browser.')
    expect(writes).toEqual([])
    expect(await(await request.get(endpoint+'/quantity-settings')).json()).toEqual(before)
    expect((await(await a.request.get(endpoint+'/quantities')).json()).projection.id).toBe(original.projection.id)
    await goSection(a,'History')
    await expect(a.locator('.result-count')).toContainText('Results: 30')
    await expect(a.getByLabel('From day (UTC+13:00)',{exact:true})).toHaveValue('2026-01-02')
    await expect(a.locator('.history-transactions tbody tr').first()).toContainText('01:00')
    const instants=[new URL(a.url()).searchParams.get('from'),new URL(a.url()).searchParams.get('to')]
    await a.getByLabel('Player',{exact:true}).fill('Synthetic Alice')
    await a.getByRole('button',{name:'Apply filters',exact:true}).click()
    expect([new URL(a.url()).searchParams.get('from'),new URL(a.url()).searchParams.get('to')]).toEqual(instants)
    await b.goto(url);await expect(b.locator('.result-count')).toContainText('Results: 30')
    await expect(b.getByLabel('From day (UTC)',{exact:true})).toHaveValue('2026-01-01')
    await expect(b.locator('.history-transactions tbody tr').first()).toContainText('12:00 PM')
    expect([new URL(b.url()).searchParams.get('from'),new URL(b.url()).searchParams.get('to')]).toEqual(instants)
    await a.reload();await expect(a.getByLabel('From day (UTC+13:00)',{exact:true})).toBeVisible()
    const saved=await a.evaluate(key=>JSON.parse(localStorage.getItem(key)!),key)
    expect(saved.version).toBe(1);expect(saved.timezone).toBe('UTC+13:00')
    expect(saved).not.toHaveProperty('filters');expect(saved).not.toHaveProperty('lastLeague')
  }finally{await first.close();await second.close()}
})

test('filter state comes only from URL, local default view is presentation and dates serialize as UTC',async({page})=>{
  await page.goto(base+'&section=settings')
  const settings=page.getByTestId('client-settings')
  await settings.getByLabel('Default view',{exact:true}).selectOption('players')
  await settings.getByLabel('Display timezone',{exact:true}).fill('Europe/Warsaw')
  await settings.getByRole('button',{name:'Save preferences',exact:true}).click()
  await goSection(page,'History')
  await page.getByLabel('Player',{exact:true}).fill('Synthetic Alice')
  await page.getByLabel('From day (Europe/Warsaw)',{exact:true}).fill('2026-03-29')
  await page.getByLabel('To day (Europe/Warsaw)',{exact:true}).fill('2026-03-29')
  await page.getByRole('button',{name:'Apply filters',exact:true}).click()
  const url=new URL(page.url())
  expect(url.searchParams.get('from')).toBe('2026-03-28T23:00:00.000Z')
  expect(url.searchParams.get('to')).toBe('2026-03-29T22:00:00.000Z')
  await page.goto(base)
  await expect(page.getByRole('navigation',{name:'League views'}).getByRole('link',{name:'Players',exact:true})).toHaveAttribute('aria-current','page')
  await expect(page.getByLabel('Player',{exact:true})).toHaveValue('')
  await expect(page.getByLabel('From day (Europe/Warsaw)',{exact:true})).toHaveValue('')
  await page.goto(url.href)
  await expect(page.getByLabel('Player',{exact:true})).toHaveValue('Synthetic Alice')
  await expect(page.getByLabel('From day (Europe/Warsaw)',{exact:true})).toHaveValue('2026-03-29')
  await page.getByRole('button',{name:'Clear filters',exact:true}).click()
  expect(new URL(page.url()).searchParams.has('from')).toBe(false)
})

test('legacy colors migrate and unavailable or corrupted storage still permits local display preferences',async({browser})=>{
  for(const denied of [false,true]){
    const context=await browser.newContext()
    try{
      await context.addInitScript(({denied,key})=>{
        if(denied)Object.defineProperty(window,'localStorage',{get(){throw new Error('Storage denied')}})
        else{localStorage.setItem(key,'invalid JSON');localStorage.setItem('poe2guild.language','pl');localStorage.setItem('poe2guild.chart-colors.v1',JSON.stringify({combined:'#112233'}))}
      },{denied,key})
      const page=await context.newPage();await page.goto('http://127.0.0.1:19003'+base+'&section=settings')
      const settings=page.getByTestId('client-settings')
      await settings.getByLabel('Display timezone',{exact:true}).fill('PST')
      await settings.getByRole('button',{name:'Save preferences',exact:true}).click()
      await expect(settings.getByLabel('Display timezone',{exact:true})).toHaveValue('UTC-08:00')
      if(denied)await expect(settings).toContainText('Browser storage is unavailable')
      else expect(await page.evaluate(key=>JSON.parse(localStorage.getItem(key)!).colors.combined,key)).toBe('#112233')
    }finally{await context.close()}
  }
})

test('sticky header and collapsible filters remain usable on desktop and mobile without changing URL data',async({page})=>{
  await page.goto(base+'&section=history&account=Synthetic%20Alice')
  await expect(page.locator('.result-count')).toContainText('Results: 30')
  const header=page.locator('.app-header'),filters=page.locator('.workspace-filters')
  for(const width of [1280,1000,390]){
    await page.setViewportSize({width,height:844})
    await page.locator('.workspace-scroll').evaluate(element=>element.scrollTo(0,800))
    await expect.poll(async()=>Math.abs((await header.boundingBox())!.y)).toBeLessThan(1)
    const filterTop=(await filters.boundingBox())!.y
    expect(filterTop).toBeGreaterThanOrEqual((await header.boundingBox())!.height)
    await page.locator('.workspace-scroll').evaluate(element=>element.scrollTo(0,1200))
    expect((await filters.boundingBox())!.y).toBe(filterTop)
    expect((await page.locator('.workspace-scroll').boundingBox())!.y).toBeGreaterThanOrEqual(filterTop+(await filters.boundingBox())!.height)
    const scroller=(await page.locator('.workspace-scroll').boundingBox())!
    expect(scroller.y+scroller.height).toBeLessThanOrEqual((await page.locator('main > footer').boundingBox())!.y+2)
    const url=page.url()
    const expanded=(await filters.boundingBox())!,handleOpen=(await filters.locator(':scope > summary').boundingBox())!
    expect(Math.abs(handleOpen.height-expanded.height)).toBeLessThan(2)
    await filters.locator(':scope > summary').click()
    await expect(filters).not.toHaveAttribute('open','')
    await expect.poll(async()=>(await filters.boundingBox())!.height).toBe(0)
    const handle=(await filters.locator(':scope > summary').boundingBox())!
    expect(handle.width).toBeLessThanOrEqual(22)
    expect(handle.height).toBeGreaterThan(40)
    const content=(await page.locator('.workspace-content').boundingBox())!
    expect(Math.abs(handle.x+handle.width-(content.x+content.width))).toBeLessThan(2)
    expect((await page.locator('.workspace-scroll').boundingBox())!.y).toBe(filterTop)
    await expect(page.getByLabel('Player',{exact:true})).toBeHidden()
    expect(page.url()).toBe(url)
    await filters.locator(':scope > summary').click()
    await expect(page.getByLabel('Player',{exact:true})).toBeVisible()
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  }
  await filters.locator(':scope > summary').click()
  await page.reload();await expect(filters).not.toHaveAttribute('open','')
  await expect(page.locator('.result-count')).toContainText('Results: 30')
})

test('color wheel, saturation and brightness update a local color without changing filters',async({page})=>{
  await page.goto(base)
  await expect(page.getByTestId('time-series-chart')).toBeVisible()
  const url=page.url()
  await page.getByRole('button',{name:'Color: Guild balance',exact:true}).click()
  const popup=page.getByRole('dialog'),wheel=popup.getByRole('slider',{name:'Color wheel',exact:true})
  await expect(wheel).toBeVisible()
  const box=(await wheel.boundingBox())!
  await page.mouse.click(box.x+box.width*.85,box.y+box.height*.5)
  await popup.getByRole('slider',{name:'Saturation',exact:true}).press('Home')
  const gray=await popup.getByLabel('Series color',{exact:true}).inputValue()
  expect(gray.slice(1,3)).toBe(gray.slice(3,5));expect(gray.slice(3,5)).toBe(gray.slice(5,7))
  await popup.getByRole('slider',{name:'Saturation',exact:true}).press('End')
  await popup.getByRole('slider',{name:'Brightness',exact:true}).press('Home')
  await expect(popup.getByLabel('Series color',{exact:true})).toHaveValue('#000000')
  await popup.getByRole('slider',{name:'Brightness',exact:true}).press('End')
  await expect(popup.getByLabel('Series color',{exact:true})).toHaveValue('#ff0000')
  await popup.getByRole('button',{name:'Close',exact:true}).click()
  expect(page.url()).toBe(url)
  await page.reload()
  await expect(page.getByTestId('time-series-chart').locator('path[stroke="#ff0000"]')).not.toHaveCount(0)
})
