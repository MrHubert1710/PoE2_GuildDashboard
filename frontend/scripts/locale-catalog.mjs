import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const pluralKeys = new Set(['zero', 'one', 'two', 'few', 'many', 'other'])
const params = text => [...new Set([...text.matchAll(/\{([a-zA-Z][\w]*)\}/g)].map(match => match[1]))].sort().join(',')
export function validateCatalog(files) {
  const result = {}
  for (const [filename, raw] of Object.entries(files)) {
    const code = filename.replace(/\.json$/, '')
    let canonical
    try { canonical = Intl.getCanonicalLocales(code)[0] } catch { throw new Error(`Invalid locale: ${filename}`) }
    if (!filename.endsWith('.json') || code !== canonical) throw new Error(`Noncanonical locale: ${filename}`)
    const catalog = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (!catalog || typeof catalog.nativeName !== 'string' || !catalog.nativeName.trim() || !catalog.messages ||
        Array.isArray(catalog.messages) || typeof catalog.messages !== 'object' ||
        Object.keys(catalog).sort().join(',') !== 'messages,nativeName') throw new Error(`Invalid metadata: ${filename}`)
    const keys = Object.keys(catalog.messages)
    if (!keys.length) throw new Error(`Empty messages: ${filename}`)
    for (const key of keys) {
      const value = catalog.messages[key]
      const forms = typeof value === 'string' ? [value] : value && !Array.isArray(value) && typeof value === 'object' &&
        typeof value.other === 'string' && Object.keys(value).every(form => pluralKeys.has(form)) ? Object.values(value) : []
      if (!forms.length || forms.some(form => typeof form !== 'string' || !form.trim())) throw new Error(`Invalid message: ${filename}:${key}`)
      if (new Set(forms.map(params)).size !== 1) throw new Error(`Plural parameters differ: ${filename}:${key}`)
    }
    result[code] = catalog
  }
  if (!result.en) throw new Error('Required en.json is missing')
  for (const [code, catalog] of Object.entries(result)) {
    if (Object.keys(catalog.messages).sort().join('\n') !== Object.keys(result.en.messages).sort().join('\n')) throw new Error(`Message keys differ: ${code}`)
    for (const [key, reference] of Object.entries(result.en.messages)) {
      const translated = catalog.messages[key]
      if (typeof translated !== typeof reference) throw new Error(`Message type differs: ${code}:${key}`)
      const representative = value => typeof value === 'string' ? value : value.other
      if (params(representative(reference)) !== params(representative(translated))) throw new Error(`Parameters differ: ${code}:${key}`)
    }
  }
  return result
}
export function loadCatalog(directory) {
  return validateCatalog(Object.fromEntries(readdirSync(directory).filter(name => name.endsWith('.json')).map(name => [name, readFileSync(join(directory, name), 'utf8')])))
}
