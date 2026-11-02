import type { Page } from '@playwright/test'
export async function gotoHistory(page: Page, path: string) {
  const url = new URL(path, 'http://127.0.0.1:19003')
  if (url.searchParams.get('view') !== 'diagnostics' && !url.searchParams.has('section')) url.searchParams.set('section', 'history')
  await page.goto(url.toString())
}
export async function goSection(page: Page, name: string) {
  await page.getByRole('navigation', { name: /League views|Widoki ligi/ }).getByRole('link', { name, exact: true }).click()
}

export async function zoomTime(page:Page){
  const nav=page.getByTestId('series-navigator'),box=(await nav.locator('svg').boundingBox())!
  await expectCenteredForGesture(page)
  const end=(await page.getByRole('slider',{name:/^(End of chart range|Koniec zakresu wykresu)$/}).boundingBox())!
  await page.mouse.move(end.x+end.width/2,end.y+end.height/2);await page.mouse.down()
  await page.mouse.move(box.x+box.width*.5,end.y+end.height/2,{steps:4});await page.mouse.up()
  await expectCenteredForGesture(page)
}
async function expectCenteredForGesture(page:Page){
  const {expect}=await import('@playwright/test')
  await expect.poll(async()=>Math.abs(Number(await page.getByTestId('navigator-window').getAttribute('x'))-350)).toBeLessThan(.001)
}
export async function zoomValues(page:Page){
  const nav=page.getByTestId('value-navigator'),end=(await page.getByRole('slider',{name:'Maximum chart value',exact:true}).boundingBox())!,start=(await page.getByRole('slider',{name:'Minimum chart value',exact:true}).boundingBox())!
  await page.mouse.move(end.x+end.width/2,end.y+end.height/2);await page.mouse.down()
  await page.mouse.move(end.x+end.width/2,(end.y+start.y)/2+end.height/2,{steps:4});await page.mouse.up()
}
export async function resetTime(page:Page){await page.getByTestId('series-navigator').locator('svg').dblclick({position:{x:5,y:15}})}
export async function resetValues(page:Page){await page.getByTestId('value-navigator').locator('svg').dblclick({position:{x:2,y:2}})}
