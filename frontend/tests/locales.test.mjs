import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, rmSync, unlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadCatalog, validateCatalog } from '../scripts/locale-catalog.mjs'
import { formatMessage } from '../src/message-format.mjs'
const en = { nativeName: 'English', messages: { greeting: 'Hello {name}', count: { one: '{count} item', other: '{count} items' } } }
const pl = { nativeName: 'Polski', messages: { greeting: 'Witaj {name}', count: { one: '{count} przedmiot', few: '{count} przedmioty', many: '{count} przedmiotów', other: '{count} przedmiotu' } } }
const files = () => structuredClone({ 'en.json': en, 'pl.json': pl })
test('catalog is discovered from files, including native names and additions/removals', () => {
  const directory = mkdtempSync(join(tmpdir(), 'poe2-locales-'))
  try {
    for (const [name, catalog] of Object.entries(files())) writeFileSync(join(directory, name), JSON.stringify(catalog))
    assert.deepEqual(Object.keys(loadCatalog(directory)), ['en', 'pl'])
    writeFileSync(join(directory, 'de.json'), JSON.stringify({ ...en, nativeName: 'Deutsch' }))
    assert.equal(loadCatalog(directory).de.nativeName, 'Deutsch')
    unlinkSync(join(directory, 'pl.json'))
    assert.deepEqual(Object.keys(loadCatalog(directory)), ['de', 'en'])
    unlinkSync(join(directory, 'en.json'))
    assert.throws(() => loadCatalog(directory), /en.json/)
  } finally { rmSync(directory, { recursive: true, force: true }) }
})
for (const [name, mutate, pattern] of [
  ['malformed JSON', f => { f['pl.json'] = '{' }, /JSON/],
  ['invalid code', f => { f['bad_locale.json'] = f['pl.json'] }, /locale/],
  ['noncanonical code', f => { f['en-us.json'] = f['en.json'] }, /locale/],
  ['missing English', f => { delete f['en.json'] }, /en.json/],
  ['invalid English', f => { f['en.json'].messages.count = [] }, /Invalid message/],
  ['missing metadata', f => { delete f['pl.json'].nativeName }, /metadata/],
  ['empty nativeName', f => { f['pl.json'].nativeName = ' ' }, /metadata/],
  ['missing key', f => { delete f['pl.json'].messages.greeting }, /keys differ/],
  ['unexpected key', f => { f['pl.json'].messages.extra = 'test' }, /keys differ/],
  ['wrong parameters', f => { f['pl.json'].messages.greeting = 'Witaj {user}' }, /Parameters differ/],
  ['wrong plural parameters', f => { f['pl.json'].messages.count.few = 'kilka' }, /Plural parameters/],
  ['missing other plural', f => { delete f['en.json'].messages.count.other }, /Invalid message/],
  ['wrong message type', f => { f['pl.json'].messages.count = '{count}' }, /type differs/],
]) test(`rejects ${name}`, () => { const f = files(); mutate(f); assert.throws(() => validateCatalog(f), pattern) })
test('English fallback, plural categories and localized numbers', () => {
  const catalogs = validateCatalog(files())
  for (const [count, expected] of [[1, '1 przedmiot'], [2, '2 przedmioty'], [5, '5 przedmiotów'], [12, '12 przedmiotów'], [22, '22 przedmioty']]) assert.equal(formatMessage(catalogs, 'pl', 'count', { count }), expected)
  assert.equal(formatMessage(catalogs, 'en', 'count', { count: 1000 }), '1\u00a0000 items')
  assert.equal(formatMessage(catalogs, 'pl', 'count', { count: 10000 }), '10\u00a0000 przedmiotów')
  delete catalogs.pl.messages.greeting // Defensive runtime fallback; build validation normally prevents this.
  assert.equal(formatMessage(catalogs, 'pl', 'greeting', { name: '<img>' }), 'Hello <img>')
  assert.equal(formatMessage(catalogs, 'xx', 'greeting', { name: 'World' }), 'Hello World')
})
test('shipped catalogs pass the same validation used by Vite', () => {
  const catalogs = loadCatalog(fileURLToPath(new URL('../src/locales/', import.meta.url)))
  assert.equal(catalogs.en.nativeName, 'English')
  assert.equal(catalogs.pl.nativeName, 'Polski')
})
